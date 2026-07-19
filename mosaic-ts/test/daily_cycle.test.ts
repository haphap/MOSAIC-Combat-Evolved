/**
 * Tests for the daily-cycle composite graph (Plan §11.2 sub-step 2E).
 *
 * Three test groups:
 *   1. ``buildDailyCycleGraph`` compiles successfully (validates the
 *      LangGraph topology is well-formed).
 *   2. End-to-end smoke: 28 mocked agents run across 29 runtime stages,
 *      portfolio_actions populated, llm_calls = 29 (no duplication
 *      from subgraph composition — Plan §11.2 design decision #7).
 *   3. Heavy CRO rejection remains in the single canonical chain; there is
 *      no asymmetric replay that can bypass a second CRO review.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage, type SystemMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AcceptedAgentOutputStore } from "../src/agents/accepted_output.js";
import {
  MACRO_AGENT_CONTRACT_VERSION,
  MACRO_AGENT_IDS,
  MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION,
  MACRO_EXECUTION_BEHAVIOR_VERSION,
  MACRO_PROMPT_BEHAVIOR_VERSION,
  MACRO_ROLE_CONTRACTS,
} from "../src/agents/macro/_contracts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import { STANDARD_SECTOR_AGENT_IDS } from "../src/agents/sector/_contracts.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { CurrentPositionsSnapshot, PortfolioAction } from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import { applyBacktestPortfolioActionsToPositions } from "../src/cli/_backtest_helpers.js";
import { submitPaperTargetDeltaOrders } from "../src/cli/commands/daily-cycle.js";
import { fakeAgentStructuredOutput, fakeSchemaValue } from "../src/cli/fake_agent_output.js";
import { buildDailyCycleGraph, DAILY_CYCLE_LAYER_NODES } from "../src/graph/daily_cycle.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ helpers / shared

const TOOL_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: { x: { type: "string" } },
  required: ["x"],
};

describe("backtest position carry-over", () => {
  it("turns day N target weights into day N+1 current_positions", () => {
    const actions: PortfolioAction[] = [
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.08,
        holding_period: "6M",
        dissent_notes: "",
      },
    ];
    const day1 = applyBacktestPortfolioActionsToPositions(
      {
        snapshot_status: "empty_confirmed",
        position_source: "empty_confirmed",
        source_error_code: null,
        position_snapshot_hash: "sha256:empty",
        positions: [],
      },
      actions,
      "2024-06-24",
    );
    const day2 = applyBacktestPortfolioActionsToPositions(day1, actions, "2024-06-25");

    expect(day1.snapshot_status).toBe("loaded");
    expect(day1.position_source).toBe("backtest_replay");
    expect(day1.positions[0]?.current_weight).toBe(0.08);
    expect(day1.positions[0]?.realized_pnl_pct).toBe(0);
    expect(day1.positions[0]?.residual_drift_pct).toBe(0);
    expect(day2.positions[0]?.holding_days).toBe(1);
  });

  it("records replay exit metadata when a target exits a position", () => {
    const previous: CurrentPositionsSnapshot = {
      snapshot_status: "loaded",
      position_source: "backtest_replay",
      source_error_code: null,
      position_snapshot_hash: "sha256:prev",
      positions: [
        {
          ticker: "600519.SH",
          current_weight: 0.08,
          cost_basis: 100,
          market_price: 112,
          unrealized_pnl_pct: 0.12,
          holding_days: 7,
          entry_date: "2024-06-17",
          source_agent: "cio",
          entry_thesis_id: "backtest:600519.SH:2024-06-17",
          last_review_date: "2024-06-23",
        },
      ],
    };

    const next = applyBacktestPortfolioActionsToPositions(
      previous,
      [
        {
          ticker: "600519.SH",
          action: "SELL",
          position_decision: "EXIT",
          position_decision_reason: "exit stale thesis",
          target_weight: 0,
          holding_period: "1M",
          dissent_notes: "",
        },
      ],
      "2024-06-24",
    );

    expect(next.snapshot_status).toBe("empty_confirmed");
    expect(next.positions).toEqual([]);
    expect(next.closed_positions).toEqual([
      {
        ticker: "600519.SH",
        exit_date: "2024-06-24",
        exit_reason: "exit stale thesis",
        realized_pnl_pct: 0.12,
        residual_drift_pct: 0,
        entry_thesis_id: "backtest:600519.SH:2024-06-17",
        holding_days: 7,
      },
    ]);
  });

  it("carries partial fills and residual target drift into the next cycle", () => {
    const previous: CurrentPositionsSnapshot = {
      snapshot_status: "loaded",
      position_source: "backtest_replay",
      source_error_code: null,
      position_snapshot_hash: "sha256:prev",
      positions: [
        {
          ticker: "600519.SH",
          current_weight: 0.1,
          cost_basis: 100,
          market_price: 100,
          unrealized_pnl_pct: 0,
          holding_days: 10,
          entry_date: "2024-06-01",
          source_agent: "cio",
          entry_thesis_id: "thesis-1",
          last_review_date: "2024-06-23",
        },
      ],
    };

    const next = applyBacktestPortfolioActionsToPositions(
      previous,
      [
        {
          ticker: "600519.SH",
          action: "SELL",
          target_weight: 0,
          delta_weight: -0.1,
          holding_period: "1M",
          dissent_notes: "",
        },
      ],
      "2024-06-24",
      {
        executionByTicker: {
          "600519.SH": { status: "partial", fill_ratio: 0.5 },
        },
      },
    );

    expect(next.positions[0]).toMatchObject({
      ticker: "600519.SH",
      current_weight: 0.05,
      residual_drift_pct: -0.05,
      holding_days: 11,
    });
    expect(next.closed_positions).toBeUndefined();
  });

  it("carries target positions across a 10-day replay loop", () => {
    const actions: PortfolioAction[] = [
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.08,
        holding_period: "6M",
        dissent_notes: "",
      },
      {
        ticker: "688981.SH",
        action: "BUY",
        target_weight: 0.06,
        holding_period: "3M",
        dissent_notes: "",
      },
    ];
    let positions: CurrentPositionsSnapshot = {
      snapshot_status: "empty_confirmed" as const,
      position_source: "empty_confirmed" as const,
      source_error_code: null,
      position_snapshot_hash: "sha256:empty",
      positions: [],
    };

    for (let day = 0; day < 10; day++) {
      positions = applyBacktestPortfolioActionsToPositions(
        positions,
        actions,
        `2024-06-${String(24 + day).padStart(2, "0")}`,
      );
    }

    expect(positions.snapshot_status).toBe("loaded");
    expect(positions.positions.map((position) => position.ticker).sort()).toEqual([
      "600519.SH",
      "688981.SH",
    ]);
    expect(positions.positions[0]?.holding_days).toBe(9);
  });
});

describe("paper target-delta execution", () => {
  it("delegates sizing to paper.suggest_order_from_signal so orders are target-current deltas", async () => {
    const api = {
      paperSuggestOrderFromSignal: vi.fn().mockResolvedValue({
        ticker: "600519.SH",
        side: "buy",
        quantity: 100,
        price: 1000,
        target_weight_pct: 8,
        rating: "BUY",
      }),
      paperBuy: vi.fn().mockResolvedValue({
        ticker: "600519.SH",
        side: "buy",
        quantity: 100,
        price: 1000,
        amount: 100000,
        commission: 30,
      }),
      paperSell: vi.fn(),
    };

    const result = await submitPaperTargetDeltaOrders(
      api as unknown as Parameters<typeof submitPaperTargetDeltaOrders>[0],
      [
        {
          ticker: "600519.SH",
          action: "BUY",
          current_weight: 0.05,
          target_weight: 0.08,
          delta_weight: 0.03,
          holding_period: "6M",
          dissent_notes: "",
        },
      ],
      { analysisId: "trace-1", tradeDate: "2024-06-24" },
    );

    expect(api.paperSuggestOrderFromSignal).toHaveBeenCalledWith(
      expect.objectContaining({
        ticker: "600519.SH",
        state: expect.objectContaining({
          backtest_signal: expect.objectContaining({
            target_weight_pct: 8,
            weight_source: "target_portfolio_weight",
          }),
        }),
      }),
    );
    expect(api.paperBuy).toHaveBeenCalledWith(
      expect.objectContaining({ ticker: "600519.SH", quantity: 100, analysis_id: "trace-1" }),
    );
    expect(api.paperBuy).toHaveBeenCalledWith(
      expect.not.objectContaining({ order_intent_key: expect.anything() }),
    );
    expect(api.paperSell).not.toHaveBeenCalled();
    expect(result[0]?.suggested_order?.quantity).toBe(100);
  });

  it("binds order intents to the frozen target and rejects a stale account snapshot", async () => {
    const baseHash = `sha256:${"1".repeat(64)}`;
    const changedHash = `sha256:${"2".repeat(64)}`;
    const finalTargetHash = `sha256:${"3".repeat(64)}`;
    const account = {
      user_id: "default",
      cash: 1_000_000,
      market_value: 0,
      total_assets: 1_000_000,
      realized_pnl: 0,
      unrealized_pnl: 0,
      total_commission: 0,
      updated_at: "2024-06-24T00:00:00Z",
    };
    const staleApi = {
      paperGetPortfolioSnapshot: vi.fn().mockResolvedValue({
        account,
        positions: [],
        snapshot_hash: changedHash,
      }),
      paperSuggestOrderFromSignal: vi.fn(),
      paperBuy: vi.fn(),
      paperSell: vi.fn(),
    };

    const stale = await submitPaperTargetDeltaOrders(
      staleApi as unknown as Parameters<typeof submitPaperTargetDeltaOrders>[0],
      [
        {
          ticker: "600519.SH",
          action: "BUY",
          current_weight: 0.05,
          target_weight: 0.08,
          delta_weight: 0.03,
          holding_period: "6M",
          dissent_notes: "",
        },
      ],
      {
        runId: "run-1",
        finalTargetHash,
        expectedAccountSnapshotHash: baseHash,
      },
    );

    expect(stale[0]).toMatchObject({
      skipped_reason: "STALE_FINAL_TARGET",
      residual_drift_weight: 0.03,
      submitted_order: null,
    });
    expect(staleApi.paperSuggestOrderFromSignal).not.toHaveBeenCalled();
  });

  it("submits a hash-bound intent and reports post-fill residual drift", async () => {
    const baseHash = `sha256:${"1".repeat(64)}`;
    const postHash = `sha256:${"2".repeat(64)}`;
    const finalTargetHash = `sha256:${"3".repeat(64)}`;
    const account = {
      user_id: "default",
      cash: 920_000,
      market_value: 80_000,
      total_assets: 1_000_000,
      realized_pnl: 0,
      unrealized_pnl: 0,
      total_commission: 0,
      updated_at: "2024-06-24T00:00:00Z",
    };
    const api = {
      paperGetPortfolioSnapshot: vi
        .fn()
        .mockResolvedValueOnce({
          account: { ...account, cash: 1_000_000 },
          positions: [],
          snapshot_hash: baseHash,
        })
        .mockResolvedValueOnce({
          account,
          positions: [{ ticker: "600519.SH", market_value: 75_000 }],
          snapshot_hash: postHash,
        }),
      paperSuggestOrderFromSignal: vi.fn().mockResolvedValue({
        ticker: "600519.SH",
        side: "buy",
        quantity: 100,
        price: 750,
        target_weight_pct: 8,
        rating: "BUY",
      }),
      paperBuy: vi.fn().mockResolvedValue({
        ticker: "600519.SH",
        side: "buy",
        quantity: 100,
        price: 750,
        amount: 75_000,
        commission: 22.5,
        fill_status: "filled",
      }),
      paperSell: vi.fn(),
    };

    const result = await submitPaperTargetDeltaOrders(
      api as unknown as Parameters<typeof submitPaperTargetDeltaOrders>[0],
      [
        {
          ticker: "600519.SH",
          action: "BUY",
          current_weight: 0.05,
          target_weight: 0.08,
          delta_weight: 0.03,
          holding_period: "6M",
          dissent_notes: "",
        },
      ],
      {
        runId: "run-1",
        finalTargetHash,
        expectedAccountSnapshotHash: baseHash,
      },
    );

    expect(api.paperBuy).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_account_snapshot_hash: baseHash,
        final_target_hash: finalTargetHash,
        order_intent_key: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
      }),
    );
    expect(result[0]?.post_submit_snapshot_hash).toBe(postHash);
    expect(result[0]?.residual_drift_weight).toBeCloseTo(0.005);
  });
});

const FAKE_TOOLS: ToolMetadata[] = [
  "get_rke_research_context",
  "get_china_macro_snapshot",
  "get_us_macro_snapshot",
  "get_eu_macro_snapshot",
  "get_central_bank_snapshot",
  "get_us_financial_conditions_snapshot",
  "get_euro_area_financial_conditions_snapshot",
  "get_commodity_conditions_snapshot",
  "get_geopolitical_events_snapshot",
  "get_market_breadth_snapshot",
  "get_market_positioning_snapshot",
  "get_sector_research_snapshot",
  "get_relationship_graph_snapshot",
  "get_superinvestor_candidate_snapshot",
  "get_cro_risk_snapshot",
  "get_alpha_candidate_snapshot",
  "get_execution_snapshot",
  "get_cio_decision_snapshot",
  "get_role_event_snapshot",
  "get_pboc_ops",
  "get_fred_series",
  "get_yield_curve_cn",
  "get_industry_policy",
  "get_policy_uncertainty",
  "get_property_data",
  "get_us_china_spread",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_usdcny",
  "get_commodity_prices",
  "get_ivx",
  "get_realized_volatility",
  "get_etf_indicator",
  "get_fund_flow",
  "get_news",
  "get_etf_price_data",
  "get_etf_info",
  "get_etf_nav",
  "get_etf_universe",
  "get_etf_holdings",
  "get_caixin_sentiment",
  "get_us_china_relations",
  "get_broker_research",
  "get_stock_research",
  "get_fundamentals",
  "get_balance_sheet",
  "get_income_statement",
  "get_cashflow",
  "get_stock_data",
  "get_indicators",
  "get_stock_moneyflow",
  "get_industry_moneyflow",
].map((name) => ({ name, description: name, args_schema: TOOL_SCHEMA }));

const fakeApi: BridgeApi = {
  toolsList: async () => FAKE_TOOLS,
  toolsCall: async (name: string) => {
    const role = MACRO_SNAPSHOT_ROLE_BY_TOOL[name];
    if (!role) return { text: `${name}_csv` };
    return {
      text: JSON.stringify({
        schema_version:
          role === "market_breadth" ? "market_breadth_snapshot_v1" : "macro_role_snapshot_v2",
        ...(role !== "market_breadth" ? { role } : {}),
        as_of_date: "2024-06-24",
      }),
    };
  },
} as unknown as BridgeApi;

const MACRO_SNAPSHOT_ROLE_BY_TOOL: Record<string, string> = {
  get_china_macro_snapshot: "china",
  get_us_macro_snapshot: "us_economy",
  get_eu_macro_snapshot: "eu_economy",
  get_central_bank_snapshot: "central_bank",
  get_us_financial_conditions_snapshot: "us_financial_conditions",
  get_euro_area_financial_conditions_snapshot: "euro_area_financial_conditions",
  get_commodity_conditions_snapshot: "commodities",
  get_geopolitical_events_snapshot: "geopolitical",
  get_market_breadth_snapshot: "market_breadth",
  get_market_positioning_snapshot: "institutional_flow",
};

const BASE_CONFIG: MosaicConfig = {
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

function emptyState(): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: "cohort_default",
    as_of_date: "2024-06-24",
    mode: "live",
    trace_id: "test",
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
    layer4_outputs: {
      cro: null,
      alpha_discovery: null,
      autonomous_execution: null,
      cio: null,
    },
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
  };
}

const ALL_AGENT_IDS = [
  // L1
  "china",
  "us_economy",
  "eu_economy",
  "central_bank",
  "us_financial_conditions",
  "euro_area_financial_conditions",
  "commodities",
  "geopolitical",
  "market_breadth",
  "institutional_flow",
  // L2
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
  "relationship_mapper",
  // L3
  "druckenmiller",
  "munger",
  "burry",
  "ackman",
  // L4
  "cro",
  "alpha_discovery",
  "autonomous_execution",
  "cio",
] as const;

function formalState(): DailyCycleStateType {
  const base = emptyState();
  const asOf = "2024-06-24T15:00:00+08:00";
  const rosterId = "production-variant-roster:fixture";
  const revisionId = "production-variant-roster-revision:fixture";
  const releaseId = "execution-behavior-release:fixture";
  const hash = (index: number) => `sha256:${index.toString(16).padStart(64, "0")}`;
  const macroIds = new Set<string>(MACRO_AGENT_IDS);
  const componentIds = new Set(
    Object.entries(MACRO_ROLE_CONTRACTS)
      .filter(([, contract]) => contract.mode === "COMPONENTS")
      .map(([agentId]) => agentId),
  );
  const behaviorBindings = Object.fromEntries(
    ALL_AGENT_IDS.map((agentId) => [
      agentId,
      {
        agent_contract_version: macroIds.has(agentId)
          ? MACRO_AGENT_CONTRACT_VERSION
          : `${agentId}_agent_contract_fixture_v2`,
        prompt_behavior_version: macroIds.has(agentId)
          ? MACRO_PROMPT_BEHAVIOR_VERSION
          : `${agentId}_prompt_fixture_v2`,
        execution_behavior_version: macroIds.has(agentId)
          ? MACRO_EXECUTION_BEHAVIOR_VERSION
          : `${agentId}_execution_fixture_v2`,
        component_weight_contract_version: componentIds.has(agentId)
          ? MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION
          : null,
        reliability_adapter_contract_version: `${agentId}_reliability_fixture_v2`,
        confidence_semantics_contract_version: `${agentId}_confidence_fixture_v2`,
      },
    ]),
  );
  const weightedAgents = ALL_AGENT_IDS.filter(
    (agentId) => !["cro", "alpha_discovery", "autonomous_execution", "cio"].includes(agentId),
  );
  const weights = weightedAgents.map((agentId, index) => ({
    agent_id: agentId,
    usage_track_key_hash: hash(100 + index),
    weight_record_id: `weight:${agentId}`,
    weight_record_hash: hash(200 + index),
    record_kind: "COLD_START_INITIALIZATION" as const,
    darwin_weight: 1,
    previous_weight_record_id: null,
    n_eligible_scores: 0,
    scoring_window_hash: hash(300 + index),
    update_event_id: null,
    effective_at: asOf,
    reliability_record_id: `reliability:${agentId}`,
    reliability_record_hash: hash(400 + index),
    operational_reliability: 1,
    operational_reliability_if_accepted: 1,
    reliability_state: "COLD_START" as const,
    accountable_count: 0,
    accepted_count: 0,
  }));
  const stageSkippedAgents = new Set(["cro", "autonomous_execution"]);
  const slots = ALL_AGENT_IDS.map((agentId, index) => {
    const scheduled = stageSkippedAgents.has(agentId);
    return {
      schema_version: "outcome_schedule_slot_v2",
      outcome_schedule_slot_id: `outcome-slot:${agentId}`,
      outcome_schedule_slot_hash: hash(500 + index),
      outcome_schedule_plan_id: "outcome-plan:fixture",
      graph_run_id: "formal-graph-run",
      agent_id: agentId,
      track_key_hash: hash(600 + index),
      run_slot_id: `run-slot:${agentId}`,
      run_slot_kind: scheduled ? ("OUTCOME_SCHEDULED" as const) : ("DOWNSTREAM_ONLY" as const),
      scheduled_sample_id: scheduled ? `scheduled-sample:${agentId}` : null,
    };
  });
  const outcomeStageSkips = Object.fromEntries(
    [...stageSkippedAgents].map((agentId, index) => {
      const slot = slots.find((row) => row.agent_id === agentId);
      if (!slot?.scheduled_sample_id) throw new Error(`missing fixture slot: ${agentId}`);
      return [
        agentId,
        {
          stage_skip_id: `stage-skip:${agentId}`,
          stage_skip_hash: hash(800 + index),
          schema_version: "no_evaluation_object_stage_skip_v2" as const,
          graph_run_id: "formal-graph-run",
          outcome_schedule_plan_id: "outcome-plan:fixture",
          outcome_schedule_slot_id: slot.outcome_schedule_slot_id,
          scheduled_sample_id: slot.scheduled_sample_id,
          track_key_hash: slot.track_key_hash,
          agent_id: agentId as "cro" | "autonomous_execution",
          skip_reason: "NO_EVALUATION_OBJECT" as const,
          frozen_object_set_id: `frozen-empty-set:${agentId}`,
          frozen_object_set_hash: hash(810 + index),
          member_count: 0 as const,
          model_invoked: false as const,
          eligibility_audit_id: `eligibility-audit:${agentId}`,
          eligibility_audit_revision_id: `eligibility-revision:${agentId}`,
          eligibility_audit_revision_hash: hash(820 + index),
          evidence_ids: [`evidence:empty-set:${agentId}`],
          causal_dedupe_key: hash(830 + index),
          recorded_at: asOf,
        },
      ];
    }),
  );
  const resolutions = Object.entries(MACRO_ROLE_CONTRACTS).flatMap(([agentId, contract]) => {
    if (contract.mode !== "COMPONENTS") return [];
    const componentIds = Object.keys(contract.components);
    const weight = 1 / componentIds.length;
    return [
      {
        agent_id: agentId,
        component_weight_contract_version: MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION,
        component_weights: Object.fromEntries(
          componentIds.map((componentId) => [componentId, weight]),
        ),
        release_revision_id: null,
        release_revision_hash: null,
        effective_at: null,
      },
    ];
  });
  return {
    ...base,
    trace_id: "formal-graph-run",
    outcome_stage_skips: outcomeStageSkips,
    darwinian_runtime_binding: {
      schema_version: "darwinian_runtime_binding_v2",
      production_variant_roster_id: rosterId,
      cohort_id: "cohort_default",
      language: "zh",
      execution_behavior_release_id: releaseId,
      prompt_repo_id: "private-prompts",
      prompt_repo_revision: "a".repeat(40),
      effective_at: asOf,
      agent_behavior_bindings: behaviorBindings,
      binding_hash: hash(700),
    },
    darwinian_weight_snapshot: {
      darwinian_snapshot_id: "darwinian-snapshot:fixture",
      darwinian_snapshot_hash: hash(701),
      schema_version: "darwinian_usage_weight_snapshot_v2",
      production_variant_roster_id: rosterId,
      production_variant_roster_revision_id: revisionId,
      execution_behavior_release_id: releaseId,
      cohort_id: "cohort_default",
      language: "zh",
      as_of: asOf,
      weights,
    },
    component_weight_snapshot: {
      component_weight_snapshot_id: "component-weight-snapshot:fixture",
      component_weight_snapshot_hash: hash(702),
      schema_version: "component_weight_runtime_snapshot_v2",
      as_of: asOf,
      resolutions,
    },
    outcome_schedule_plan: {
      outcome_schedule_plan_id: "outcome-plan:fixture",
      outcome_schedule_plan_hash: hash(703),
      schema_version: "outcome_schedule_plan_v2",
      graph_run_id: "formal-graph-run",
      production_variant_roster_id: rosterId,
      production_variant_roster_revision_id: revisionId,
      execution_behavior_release_id: releaseId,
      cohort_id: "cohort_default",
      language: "zh",
      as_of: asOf,
      prepared_at: asOf,
      slots,
    },
  };
}

// L4 layer subdir mapping
const AGENT_SUBDIR: Record<string, string> = {
  china: "macro",
  us_economy: "macro",
  eu_economy: "macro",
  central_bank: "macro",
  us_financial_conditions: "macro",
  euro_area_financial_conditions: "macro",
  commodities: "macro",
  geopolitical: "macro",
  market_breadth: "macro",
  institutional_flow: "macro",
  semiconductor: "sector",
  technology: "sector",
  energy: "sector",
  biotech: "sector",
  consumer: "sector",
  industrials: "sector",
  real_estate_construction: "sector",
  financials: "sector",
  agriculture: "sector",
  relationship_mapper: "sector",
  druckenmiller: "superinvestor",
  munger: "superinvestor",
  burry: "superinvestor",
  ackman: "superinvestor",
  cro: "decision",
  alpha_discovery: "decision",
  autonomous_execution: "decision",
  cio: "decision",
};

// ============================================================ scripted LLM (28 agents)

class ScriptedLlm28 {
  invokeCalls = 0;
  bindToolsCalls = 0;
  structuredCalls = 0;
  perAgentStructuredCount: Record<string, number> = {};
  // Sorted by descending name length so e.g. "alpha_discovery" matches before
  // "alpha" (no current overlaps but defensive).
  readonly sortedAgentIds: string[];
  private tools: Array<{ name: string; schema?: unknown }> = [];

  constructor() {
    this.sortedAgentIds = [...ALL_AGENT_IDS].sort((a, b) => b.length - a.length);
  }

  bindTools(tools: unknown): ScriptedLlm28 {
    this.bindToolsCalls++;
    this.tools = Array.isArray(tools) ? tools : [];
    return this;
  }

  withStructuredOutput(schema: unknown): { invoke: (input: unknown) => Promise<unknown> } {
    return {
      invoke: async (input: unknown) => {
        this.structuredCalls++;
        const msgs = input as BaseMessage[];
        const sys = msgs[0] as SystemMessage | undefined;
        const sysContent = typeof sys?.content === "string" ? sys.content : "";
        const runtimeMarkerAgent = this.sortedAgentIds.find((agent) =>
          sysContent.includes(`Runtime agent id: ${agent}\n`),
        );
        for (const agent of runtimeMarkerAgent ? [runtimeMarkerAgent] : this.sortedAgentIds) {
          if (runtimeMarkerAgent === agent || sysContent.includes(`the ${agent} `)) {
            this.perAgentStructuredCount[agent] = (this.perAgentStructuredCount[agent] ?? 0) + 1;
            return fakeAgentStructuredOutput(schema, agent, input);
          }
        }
        throw new Error(
          `ScriptedLlm28: no fake response matched system: ${sysContent.slice(0, 120)}`,
        );
      },
    };
  }

  async invoke(messages: BaseMessage[]): Promise<AIMessage> {
    this.invokeCalls++;
    if (this.tools.length > 0 && !messages.some((message) => message._getType() === "tool")) {
      return new AIMessage({
        content: "",
        tool_calls: this.tools.map((tool, index) => ({
          id: `fake-tool-${index}`,
          name: tool.name,
          args: fakeSchemaValue(tool.schema),
        })),
      });
    }
    return new AIMessage("analysis text for the daily cycle");
  }
}

// ============================================================ compile sanity

describe("buildDailyCycleGraph (compile-only)", () => {
  beforeEach(() => clearPromptCache());
  afterEach(() => clearPromptCache());

  it("compiles without throwing and exposes the canonical layer node names", () => {
    expect([...DAILY_CYCLE_LAYER_NODES]).toEqual(["layer1", "layer2", "layer3", "layer4"]);
    const handle: LlmHandle = {
      llm: new ScriptedLlm28() as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };
    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
    });
    expect(graph).toBeDefined();
  });
});

// ============================================================ end-to-end smoke

describe("buildDailyCycleGraph (end-to-end smoke, no veto)", () => {
  let promptDir: string;

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-dc-"));
    for (const agent of ALL_AGENT_IDS) {
      const subdir = AGENT_SUBDIR[agent] as string;
      const dir = join(promptDir, "cohort_default", subdir);
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, `${agent}.zh.md`), "FAKE", "utf-8");
      writeFileSync(join(dir, `${agent}.en.md`), "FAKE", "utf-8");
    }
    clearPromptCache();
  });

  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("runs all 28 agents through 29 stages and publishes a validated final target", async () => {
    const llm = new ScriptedLlm28();
    const logs: string[] = [];
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
      agentTimeoutSeconds: 0,
      onLog: (msg) => logs.push(msg),
    });

    const final = (await graph.invoke(emptyState())) as DailyCycleStateType;

    // L1 — ten accepted transmissions plus the deterministic completeness gate.
    expect(Object.keys(final.layer1_outputs)).toHaveLength(10);
    expect(final.macro_input_gate?.accepted_agent_ids).toHaveLength(10);

    // L2 — nine standard sectors plus relationship mapper.
    expect(Object.keys(final.layer2_outputs)).toHaveLength(10);

    // L3 — 4 superinvestor outputs
    expect(Object.keys(final.layer3_outputs)).toHaveLength(4);

    // L4 — all 4 slots populated
    expect(final.layer4_outputs.cro).not.toBeNull();
    expect(final.layer4_outputs.alpha_discovery).not.toBeNull();
    expect(final.layer4_outputs.autonomous_execution).not.toBeNull();
    expect(final.layer4_outputs.cio).not.toBeNull();

    // Top-level mirror
    expect(final.portfolio_actions).toEqual([]);
    expect(final.layer4_outputs.cio?.decision_disposition).toBe("ALL_CASH");

    // Empty frozen CRO/execution object sets are deterministic stage skips;
    // standard Sector agents still use research + final and CIO runs twice.
    expect(llm.structuredCalls).toBe(36);
    expect(Object.keys(llm.perAgentStructuredCount).length).toBe(26);
    for (const agent of ALL_AGENT_IDS) {
      if (agent === "cro" || agent === "autonomous_execution") {
        expect(llm.perAgentStructuredCount[agent]).toBeUndefined();
        continue;
      }
      expect(llm.perAgentStructuredCount[agent]).toBe(
        agent === "cio" || STANDARD_SECTOR_AGENT_IDS.includes(agent as never) ? 2 : 1,
      );
    }

    expect(final.llm_calls).toHaveLength(27);
    expect(
      final.llm_calls.every((call) =>
        ["accepted", "accepted_empty"].includes(call.agent_run_audit?.status ?? ""),
      ),
    ).toBe(true);
    expect(final.replay_triggered).toBe(false);
    const runtime = final.layer4_outputs.runtime;
    expect(runtime?.l4_run_snapshot_bundle).toMatchObject({
      schema_version: "decision.l4_run_snapshot_bundle.v1",
      frozen: true,
    });
    expect(runtime?.l4_run_snapshot_bundle?.prompt_snapshots).toHaveLength(5);
    expect(runtime?.l4_run_snapshot_bundle?.bundle_hash).toMatch(/^sha256:/);
    for (const snapshot of runtime?.l4_run_snapshot_bundle?.prompt_snapshots ?? []) {
      expect(snapshot.prompt_source_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
      if (snapshot.private_knot_snapshot_hash) {
        expect(snapshot.private_knot_snapshot_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
      }
    }
    expect(runtime?.l4_run_snapshot_bundle?.position_snapshot_hash).toMatch(
      /^sha256:[0-9a-f]{64}$/,
    );
    expect(runtime?.candidate_target_state?.frozen).toBe(true);
    expect(runtime?.candidate_target_state?.market_data_vintage_hash).toMatch(/^sha256:/);
    expect(runtime?.cro_review_state?.candidate_target_hash).toBe(
      runtime?.candidate_target_state?.candidate_target_hash,
    );
    expect(runtime?.execution_feasibility_state?.candidate_target_hash).toBe(
      runtime?.candidate_target_state?.candidate_target_hash,
    );
    expect(
      new Set([
        runtime?.candidate_target_state?.l4_run_snapshot_hash,
        runtime?.position_review_state?.l4_run_snapshot_hash,
        runtime?.portfolio_exposure_state?.l4_run_snapshot_hash,
        runtime?.cro_review_state?.l4_run_snapshot_hash,
        runtime?.execution_feasibility_state?.l4_run_snapshot_hash,
        runtime?.final_target_state?.l4_run_snapshot_hash,
        runtime?.portfolio_summary?.l4_run_snapshot_hash,
      ]),
    ).toEqual(new Set([runtime?.l4_run_snapshot_bundle?.bundle_hash]));
    expect(runtime?.final_target_state?.final_target_hash).toMatch(/^sha256:/);
    expect(runtime?.final_target_state?.market_data_vintage_hash).toBe(
      runtime?.candidate_target_state?.market_data_vintage_hash,
    );
    expect(runtime?.final_target_state?.liquidity_vintage_hash).toBe(
      runtime?.execution_feasibility_state?.liquidity_vintage_hash,
    );
    expect(runtime?.portfolio_summary).toMatchObject({
      schema_version: "portfolio.summary.v1",
      final_target_hash: runtime?.final_target_state?.final_target_hash,
      target_weight_sum: 0,
      gross_exposure: 0,
      net_exposure: 0,
      leverage_authorized: false,
      frozen: true,
    });
    expect(runtime?.portfolio_summary?.cash_weight).toBe(1);
    expect(runtime?.portfolio_summary?.summary_hash).toMatch(/^sha256:/);
    expect(
      runtime?.stage_trace
        .filter((entry) => entry.operation === "agent_run")
        .map((entry) => entry.stage),
    ).toEqual(["alpha_discovery", "cio_proposal", "cio_final"]);
    expect(runtime?.stage_trace.at(-1)?.stage).toBe("shared_validation");
    expect(runtime?.stage_trace[0]).toMatchObject({
      stage: "l4_snapshot_freeze",
      operation: "source_freeze",
      output_hashes: { l4_run_snapshot_bundle: runtime?.l4_run_snapshot_bundle?.bundle_hash },
    });
    expect(logs).toContainEqual(
      expect.stringContaining("[agent:start] L1 central_bank timeout=off"),
    );
    expect(logs).toContainEqual(expect.stringContaining("[agent:done] L4 cio"));
    expect(logs).toContainEqual(expect.stringContaining("actions=0"));
  });

  it("transports formal cross-layer outputs only through accepted record refs", async () => {
    const llm = new ScriptedLlm28();
    const acceptedOutputStore = new AcceptedAgentOutputStore();
    const graph = buildDailyCycleGraph({
      llmHandle: {
        llm: llm as unknown as LlmHandle["llm"],
        provider: "fake",
        model: "fake-model",
        baseUrl: undefined,
      },
      api: fakeApi,
      config: BASE_CONFIG,
      acceptedOutputStore,
      agentTimeoutSeconds: 0,
    });

    const final = (await graph.invoke(formalState())) as DailyCycleStateType;
    const records = acceptedOutputStore.records();

    expect(Object.keys(final.layer1_outputs)).toHaveLength(0);
    expect(Object.keys(final.layer2_outputs)).toHaveLength(0);
    expect(Object.keys(final.layer3_outputs)).toHaveLength(0);
    expect(Object.keys(final.accepted_output_refs)).toHaveLength(27);
    expect(records).toHaveLength(27);
    expect(Object.keys(final.outcome_stage_skips).sort()).toEqual(["autonomous_execution", "cro"]);
    expect(records.filter((record) => record.agent_id === "cio")).toHaveLength(2);
    expect(records.every((record) => record.graph_run_id === "formal-graph-run")).toBe(true);
    expect(
      records.every(
        (record) =>
          "component_weight_contract_version" in record &&
          "reliability_adapter_contract_version" in record &&
          "confidence_semantics_contract_version" in record,
      ),
    ).toBe(true);
    expect(
      records.every(
        (record) =>
          !("verified_claim_graph" in (record.output.payload as Record<string, unknown>)) &&
          !("verified_claim_audit" in (record.output.payload as Record<string, unknown>)),
      ),
    ).toBe(true);
    expect(final.macro_input_gate?.accepted_count).toBe(10);
    expect(final.layer4_outputs.runtime?.final_target_state?.frozen).toBe(true);
  });
});

// ============================================================ canonical no-replay branch

describe("buildDailyCycleGraph (heavy CRO rejection)", () => {
  let promptDir: string;

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-dc-veto-"));
    for (const agent of ALL_AGENT_IDS) {
      const subdir = AGENT_SUBDIR[agent] as string;
      const dir = join(promptDir, "cohort_default", subdir);
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, `${agent}.zh.md`), "FAKE", "utf-8");
      writeFileSync(join(dir, `${agent}.en.md`), "FAKE", "utf-8");
    }
    clearPromptCache();
  });

  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("keeps one hash-bound canonical pass when CRO rejects most candidates", async () => {
    const llm = new ScriptedLlm28();
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
    });

    const final = (await graph.invoke(emptyState())) as DailyCycleStateType;

    expect(llm.structuredCalls).toBe(36);
    expect(llm.perAgentStructuredCount.cro).toBeUndefined();
    expect(llm.perAgentStructuredCount.alpha_discovery).toBe(1);
    expect(llm.perAgentStructuredCount.autonomous_execution).toBeUndefined();
    expect(llm.perAgentStructuredCount.cio).toBe(2);
    expect(final.llm_calls).toHaveLength(27);
    expect(final.portfolio_actions).toEqual([]);
    expect(final.replay_triggered).toBe(false);
    expect(final.layer4_outputs.runtime?.cro_review_state?.output).toMatchObject({
      review_disposition: "NO_OBJECTION",
      rejected_picks: [],
    });
    expect(final.layer4_outputs.runtime?.stage_trace.at(-1)).toMatchObject({
      stage: "shared_validation",
      status: "completed",
    });
    expect(final.layer4_outputs.runtime?.portfolio_summary).toMatchObject({
      target_weight_sum: 0,
      cash_weight: 1,
      validator_results: [
        expect.objectContaining({
          status: "accepted",
          reason_codes: [],
        }),
      ],
    });
  });

  it("end branch (no replay) when cro rejects 0 picks even with full L3 pool", async () => {
    const llm = new ScriptedLlm28();
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
    });
    await graph.invoke(emptyState());
    expect(llm.structuredCalls).toBe(36);
  });
});

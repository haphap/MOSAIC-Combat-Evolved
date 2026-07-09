import { render } from "ink-testing-library";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { Dashboard } from "../src/tui/Dashboard.js";

function fakeApi() {
  return {
    scorecardLatestCioActions: vi.fn().mockResolvedValue({
      cohort: "cohort_default",
      date: "2026-05-30",
      actions: [
        {
          ticker: "512880.SH",
          action: "BUY",
          position_decision: "ADD",
          current_weight_pct: 1.1,
          target_weight_pct: 15,
          delta_weight_pct: 13.9,
          thesis_status: "intact",
          risk_flags_json: JSON.stringify(["target_current_drift"]),
          declared_knob_influence_ids_json: JSON.stringify(["mirofish_portfolio_stress_weight"]),
          declared_influence_rationale: "scenario stress tempered add size",
          verified_knob_audit_json: JSON.stringify({
            fired_cap_ids: ["fallback_primary_tool"],
            unsupported_knob_influence_ids: [],
          }),
          decision_agent_audits_json: JSON.stringify({
            cro: {
              fired_cap_ids: ["missing_current_data"],
              declared_knob_influence_ids: ["stop_loss_pct"],
              unsupported_knob_influence_ids: [],
            },
            autonomous_execution: {
              fired_cap_ids: [],
              declared_knob_influence_ids: ["mirofish_path_sizing_weight"],
              unsupported_knob_influence_ids: [],
            },
            cio: {
              fired_cap_ids: ["fallback_primary_tool"],
              declared_knob_influence_ids: ["mirofish_portfolio_stress_weight"],
              unsupported_knob_influence_ids: [],
            },
          }),
          override_reason: "CRO reviewed current data",
          dissent_notes: "",
          rationale_snapshot: "券商β",
          forward_return_5d: null,
          scored_at: null,
        },
      ],
    }),
    scorecardWinRate: vi.fn().mockResolvedValue({
      rows: [{ ticker: "510300.SH", win_rate: 0.62, n: 13, avg_dir_return_5d: 0.008 }],
    }),
    scorecardListSkill: vi.fn().mockResolvedValue({
      rows: [{ agent: "druckenmiller", mean_alpha_5d: 0.012, sharpe_window: 1.5, n_obs: 20 }],
    }),
    paperGetAccount: vi.fn().mockResolvedValue({
      user_id: "default",
      cash: 990000,
      market_value: 10000,
      total_assets: 1000000,
      realized_pnl: 0,
      unrealized_pnl: 500,
      total_commission: 5,
      updated_at: "",
    }),
    paperGetPositions: vi.fn().mockResolvedValue([
      {
        ticker: "510300.SH",
        name: "ETF",
        quantity: 1000,
        available_qty: 1000,
        avg_cost: 10,
        current_price: 10.5,
        market_value: 10500,
        unrealized_pnl: 500,
        pnl_pct: 5,
        updated_at: "2026-05-29",
      },
    ]),
    paperGetTrades: vi.fn().mockResolvedValue([
      {
        id: 9,
        user_id: "default",
        ticker: "512880.SH",
        name: "ETF",
        side: "buy",
        quantity: 3000,
        price: 1.23,
        amount: 3690,
        commission: 5,
        pnl: null,
        analysis_id: "cli-1",
        created_at: "2026-05-30T15:01:00Z",
      },
    ]),
    backtestListRuns: vi.fn().mockResolvedValue({
      runs: [
        {
          id: 7,
          cohort: "cohort_default",
          start_date: "2026-05-20",
          end_date: "2026-05-30",
          prompt_commit_hash: "prompt",
          completed_at: "2026-05-30T00:00:00Z",
          created_at: "2026-05-30T00:00:00Z",
          action_count: 12,
          distinct_trade_days: 10,
          first_trade_date: "2026-05-20",
          last_trade_date: "2026-05-30",
        },
      ],
    }),
    backtestActionSummary: vi.fn().mockResolvedValue({
      run_id: 7,
      action_count: 12,
      trade_day_count: 10,
      first_trade_date: "2026-05-20",
      last_trade_date: "2026-05-30",
      ticker_count: 3,
      turnover_proxy: 0.42,
      max_observed_holding_days: 9,
      stale_thesis_proxy_count: 1,
      action_counts: { BUY: 6, HOLD: 2, REDUCE: 3, SELL: 1 },
      holding_period_counts: { "3M": 5, "6M": 7 },
      metric_availability: {
        turnover: "stage1_proxy_from_target_weight_changes",
        holding_days: "stage1_observed_trade_day_count",
        exit_after_hold_alpha: "requires_stage2_scored_positions",
        reduce_opportunity_cost: "requires_stage2_scored_positions",
        stop_loss_avoided_drawdown: "requires_stage2_scored_positions",
      },
    }),
    prismListCohorts: vi.fn().mockResolvedValue({
      cohorts: [
        {
          name: "cohort_default",
          start: "",
          end: "",
          description: "",
          has_branch: false,
          n_runs: 3,
          last_run_date: "2026-05-30",
        },
      ],
    }),
    mirofishGetContext: vi.fn().mockResolvedValue({
      context: {
        n_scenarios: 5,
        scenario_count: 5,
        horizon_days: 30,
        as_of_date: "2026-05-30",
        context_hash: "sha256:miro",
        generator_version: "mirofish_context_v1",
        regime: "RISK_OFF",
        narrative: "急跌回调",
        csi300_return: -0.12,
        hct_ticker: "000300.SH",
        hct_direction: "SHORT",
        hct_csi300_return: -0.35,
        tail_summary: "Crash: CSI300 -35.0% (p=5%)",
        position_stress: [
          {
            ticker: "510300.SH",
            tail_loss: -0.12,
            scenario_agreement: 0.8,
            suggested_action: "REDUCE",
          },
        ],
        engine: "swarm",
        date: "2026-05-30",
      },
    }),
    mirofishGetHistory: vi.fn().mockResolvedValue({
      history: [
        {
          id: 1,
          date: "2026-05-29",
          agent: "druckenmiller",
          scenario_type: "all",
          n_scenarios: 5,
          avg_score: 0.62,
          detail_json: null,
          created_at: "",
        },
      ],
    }),
    configGet: vi.fn().mockResolvedValue({
      llm_provider: "anthropic",
      deep_think_llm: "claude-opus",
      quick_think_llm: "claude-haiku",
      output_language: "Chinese",
      active_cohort: "euphoria_2021",
      autoresearch: {
        agent_mutation_cooldown_hours: 24,
        keep_revert_lockout_days: 3,
        keep_threshold_delta_sharpe: 0.1,
        monthly_modification_cap_per_cohort: 100,
        evaluation_horizon_trading_days: 5,
        git: { push: false, remote: "origin" },
      },
      mirofish: { engine: "montecarlo", scorer: "terminal", inject_context: false },
    }),
    configDefault: vi.fn().mockResolvedValue({}),
    configSave: vi.fn().mockImplementation((c) => Promise.resolve(c)),
  };
}

const flush = () => new Promise((r) => setTimeout(r, 20));
const mount = (api: ReturnType<typeof fakeApi>) =>
  render(createElement(Dashboard, { api: api as never, cohort: "cohort_default" }));

describe("Dashboard", () => {
  it("renders the Today (CIO plan) tab by default", async () => {
    const api = fakeApi();
    const { lastFrame } = mount(api);
    await flush();
    expect(api.scorecardLatestCioActions).toHaveBeenCalledWith("cohort_default");
    expect(lastFrame()).toContain("today's CIO plan (2026-05-30)");
    expect(lastFrame()).toContain("positions loaded 1 reviewed 1/1");
    expect(lastFrame()).toContain("UNREVIEWED_POSITION");
    expect(lastFrame()).toContain("POSITION_DATA_STALE");
    expect(lastFrame()).toContain("TARGET_CURRENT_DRIFT");
    expect(lastFrame()).toContain("ADD");
    expect(lastFrame()).toContain("intact");
    expect(lastFrame()).toContain("target_current_drift");
    expect(lastFrame()).toContain("caps=fallback_primary_tool");
    expect(lastFrame()).toContain("influence=mirofish_portfolio_stress_weight");
    expect(lastFrame()).toContain("agent detail cro caps=missing_current_data");
    expect(lastFrame()).toContain("CRO reviewed current data");
    expect(lastFrame()).toContain("512880.SH");
  });

  it("switches to the WinRate tab on key '2'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("2");
    await flush();
    expect(lastFrame()).toContain("510300.SH");
    expect(lastFrame()).toContain("62.0%");
  });

  it("switches to the skill tab on key '3'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("3");
    await flush();
    expect(lastFrame()).toContain("druckenmiller");
  });

  it("switches to the paper tab on key '4'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("4");
    await flush();
    expect(lastFrame()).toContain("total 1000000.00");
    expect(lastFrame()).toContain("paper target-delta execution");
    expect(lastFrame()).toContain("required_delta");
    expect(lastFrame()).toContain("submitted buy 3000");
    expect(lastFrame()).toContain("filled buy 3000@1.23");
    expect(lastFrame()).toContain("residual 13.9%");
    expect(lastFrame()).toContain("recent backtest carry-over");
    expect(lastFrame()).toContain("#7");
    expect(lastFrame()).toContain("trade_days  10");
    expect(lastFrame()).toContain("turnover_proxy 0.420");
    expect(lastFrame()).toContain("hold_days   9");
    expect(lastFrame()).toContain("stale_thesis   1");
    expect(lastFrame()).toContain("buy=6 reduce=3 exit=1");
    expect(lastFrame()).toContain("requires_stage2_scored_positions");
  });

  it("switches to the cohorts tab on key '5'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("5");
    await flush();
    expect(lastFrame()).toContain("2026-05-30");
  });

  it("switches to the mirofish tab on key '6' (context + runs)", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("6");
    await flush();
    expect(api.mirofishGetContext).toHaveBeenCalled();
    expect(lastFrame()).toContain("RISK_OFF"); // scenario context
    expect(lastFrame()).toContain("hash=sha256:miro");
    expect(lastFrame()).toContain("simulation_only=current_data_gate_required");
    expect(lastFrame()).toContain("SHORT 000300.SH"); // highest-conviction
    expect(lastFrame()).toContain("510300.SH"); // per-position stress
    expect(lastFrame()).toContain("REDUCE");
    expect(lastFrame()).toContain("druckenmiller"); // recent training run
  });

  it("mirofish tab degrades when no context", async () => {
    const api = fakeApi();
    api.mirofishGetContext = vi.fn().mockResolvedValue({ context: null });
    api.mirofishGetHistory = vi.fn().mockResolvedValue({ history: [] });
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("6");
    await flush();
    expect(lastFrame()).toContain("no scenario context");
  });

  it("refetches on key 'r'", async () => {
    const api = fakeApi();
    const { stdin } = mount(api);
    await flush();
    expect(api.scorecardWinRate).toHaveBeenCalledTimes(1);
    stdin.write("r");
    await flush();
    expect(api.scorecardWinRate).toHaveBeenCalledTimes(2);
  });

  it("shows a friendly message on the paper tab when not logged in", async () => {
    const api = fakeApi();
    api.paperGetAccount = vi.fn().mockRejectedValue(new Error("not logged in"));
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("4");
    await flush();
    expect(lastFrame()).toContain("no paper account");
  });

  it("switches to the settings tab on key '7' and loads config", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("7");
    await flush();
    expect(api.configGet).toHaveBeenCalled();
    expect(lastFrame()).toContain("settings (persisted to ~/.mosaic/config.json)");
    expect(lastFrame()).toContain("LLM provider");
    expect(lastFrame()).toContain("anthropic");
  });

  it("toggles a bool field with space and persists on 's'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("7");
    await flush();
    // Move to "AR git push" (a bool) and toggle it on, then save.
    for (let i = 0; i < 10; i++) stdin.write("\u001B[B"); // down arrow ×10 → AR git push
    await flush();
    stdin.write(" ");
    await flush();
    stdin.write("s");
    await flush();
    expect(api.configSave).toHaveBeenCalledWith(
      expect.objectContaining({
        autoresearch: expect.objectContaining({ git: { push: true, remote: "origin" } }),
      }),
    );
    expect(lastFrame()).toContain("saved");
  });

  it("edits a string field via enter + typing + enter", async () => {
    const api = fakeApi();
    const { stdin } = mount(api);
    await flush();
    stdin.write("7");
    await flush();
    stdin.write("\u001B[B"); // down → Deep-think model (string)
    await flush();
    stdin.write("\r"); // enter → edit mode
    await flush();
    // Clear then type a new value (buffer starts as current value).
    for (let i = 0; i < 20; i++) stdin.write("\u007F"); // backspace
    stdin.write("gpt-4o");
    await flush();
    stdin.write("\r"); // commit
    await flush();
    stdin.write("s");
    await flush();
    expect(api.configSave).toHaveBeenCalledWith(
      expect.objectContaining({ deep_think_llm: "gpt-4o" }),
    );
  });

  it("does not quit on 'q' while editing a settings field", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("7");
    await flush();
    stdin.write("\u001B[B"); // → string field
    await flush();
    stdin.write("\r"); // enter edit mode
    await flush();
    stdin.write("q"); // should be captured as text, NOT a quit
    await flush();
    // Still on settings, in edit mode (buffer shows the cursor).
    expect(lastFrame()).toContain("[esc] cancel");
  });

  it("unmounts on 'q' without throwing", async () => {
    const api = fakeApi();
    const { stdin, unmount } = mount(api);
    await flush();
    stdin.write("q");
    await flush();
    unmount();
  });
});

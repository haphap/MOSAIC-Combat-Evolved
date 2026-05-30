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
          target_weight_pct: 15,
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
        updated_at: "",
      },
    ]),
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
  });

  it("switches to the cohorts tab on key '5'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = mount(api);
    await flush();
    stdin.write("5");
    await flush();
    expect(lastFrame()).toContain("2026-05-30");
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

  it("unmounts on 'q' without throwing", async () => {
    const api = fakeApi();
    const { stdin, unmount } = mount(api);
    await flush();
    stdin.write("q");
    await flush();
    unmount();
  });
});

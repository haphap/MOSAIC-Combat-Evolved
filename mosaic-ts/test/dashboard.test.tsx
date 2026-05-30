import { render } from "ink-testing-library";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { Dashboard } from "../src/tui/Dashboard.js";

function fakeApi() {
  return {
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

describe("Dashboard", () => {
  it("renders the skill tab by default", async () => {
    const api = fakeApi();
    const { lastFrame } = render(
      createElement(Dashboard, { api: api as never, cohort: "cohort_default" }),
    );
    await flush();
    expect(api.scorecardListSkill).toHaveBeenCalledWith("cohort_default");
    expect(lastFrame()).toContain("druckenmiller");
    expect(lastFrame()).toContain("1 skill");
  });

  it("switches to the paper tab on key '2'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = render(
      createElement(Dashboard, { api: api as never, cohort: "cohort_default" }),
    );
    await flush();
    stdin.write("2");
    await flush();
    expect(lastFrame()).toContain("total 1000000.00");
    expect(lastFrame()).toContain("510300.SH");
  });

  it("switches to the cohorts tab on key '3'", async () => {
    const api = fakeApi();
    const { stdin, lastFrame } = render(
      createElement(Dashboard, { api: api as never, cohort: "cohort_default" }),
    );
    await flush();
    stdin.write("3");
    await flush();
    expect(lastFrame()).toContain("cohort_default");
    expect(lastFrame()).toContain("2026-05-30");
  });

  it("refetches on key 'r'", async () => {
    const api = fakeApi();
    const { stdin } = render(
      createElement(Dashboard, { api: api as never, cohort: "cohort_default" }),
    );
    await flush();
    expect(api.prismListCohorts).toHaveBeenCalledTimes(1);
    stdin.write("r");
    await flush();
    expect(api.prismListCohorts).toHaveBeenCalledTimes(2);
  });

  it("shows a friendly message on the paper tab when not logged in", async () => {
    const api = fakeApi();
    api.paperGetAccount = vi.fn().mockRejectedValue(new Error("not logged in"));
    const { stdin, lastFrame } = render(
      createElement(Dashboard, { api: api as never, cohort: "cohort_default" }),
    );
    await flush();
    stdin.write("2");
    await flush();
    expect(lastFrame()).toContain("no paper account");
  });

  it("unmounts on 'q' without throwing", async () => {
    const api = fakeApi();
    const { stdin, unmount } = render(
      createElement(Dashboard, { api: api as never, cohort: "cohort_default" }),
    );
    await flush();
    stdin.write("q");
    await flush();
    unmount(); // no setState-after-unmount warning
  });
});

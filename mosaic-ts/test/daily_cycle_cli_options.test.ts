import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadCurrentPositionsFixture } from "../src/cli/commands/daily-cycle.js";

function fixturePosition(ticker = "600519.SH") {
  return {
    ticker,
    current_weight: 0.08,
    cost_basis: 1500,
    market_price: 1700,
    unrealized_pnl_pct: 0.12,
    holding_days: 42,
    entry_date: "2026-05-28",
    source_agent: "cio",
    entry_thesis_id: `fixture:${ticker}`,
    last_review_date: "2026-07-08",
  };
}

describe("daily-cycle current-position fixture options", () => {
  it("parses inline current positions JSON", () => {
    const snapshot = loadCurrentPositionsFixture({
      currentPositionsJson: JSON.stringify([fixturePosition()]),
    });

    expect(snapshot?.snapshot_status).toBe("loaded");
    expect(snapshot?.position_source).toBe("cli_fixture");
    expect(snapshot?.positions[0]?.ticker).toBe("600519.SH");
    expect(snapshot?.position_snapshot_hash).toMatch(/^sha256:/);
  });

  it("loads current positions fixture files", () => {
    const dir = mkdtempSync(join(tmpdir(), "mosaic-daily-cycle-cli-"));
    const file = join(dir, "positions.json");
    try {
      writeFileSync(
        file,
        JSON.stringify({
          current_positions: [
            fixturePosition("600519.SH"),
            fixturePosition("688981.SH"),
            fixturePosition("300750.SZ"),
          ],
        }),
      );

      const snapshot = loadCurrentPositionsFixture({ currentPositionsFile: file });

      expect(snapshot?.snapshot_status).toBe("loaded");
      expect(snapshot?.positions.map((position) => position.ticker).sort()).toEqual([
        "300750.SZ",
        "600519.SH",
        "688981.SH",
      ]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("rejects malformed position fixtures before running agents", () => {
    const bad = { ...fixturePosition(), market_price: "1700" };

    expect(() =>
      loadCurrentPositionsFixture({ currentPositionsJson: JSON.stringify([bad]) }),
    ).toThrow(/market_price must be a finite number/);
  });

  it("rejects ambiguous inline and file fixture inputs", () => {
    expect(() =>
      loadCurrentPositionsFixture({
        currentPositionsJson: JSON.stringify([fixturePosition()]),
        currentPositionsFile: "/tmp/unused-positions.json",
      }),
    ).toThrow(/choose only one current-position fixture source/);
  });
});

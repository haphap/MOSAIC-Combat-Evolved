import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadMirofishPortfolioInputs } from "../src/cli/commands/mirofish.js";

describe("mirofish CLI portfolio input options", () => {
  it("parses inline current positions and exposure JSON", async () => {
    const inputs = await loadMirofishPortfolioInputs({
      currentPositionsJson: JSON.stringify([
        {
          ticker: "600519.SH",
          market_price: 1700,
          current_weight: 0.08,
          cost_basis: 1500,
          holding_days: 42,
          unrealized_pnl_pct: 0.12,
          entry_thesis: "brand moat",
        },
      ]),
      sectorExposureJson: JSON.stringify({ consumer: 0.08 }),
      themeExposureJson: JSON.stringify({ premium_consumption: 0.08 }),
    });

    expect(inputs.current_positions).toEqual([
      {
        ticker: "600519.SH",
        market_price: 1700,
        current_weight: 0.08,
        cost_basis: 1500,
        holding_days: 42,
        unrealized_pnl_pct: 0.12,
        entry_thesis: "brand moat",
      },
    ]);
    expect(inputs.sector_exposure).toEqual({ consumer: 0.08 });
    expect(inputs.theme_exposure).toEqual({ premium_consumption: 0.08 });
  });

  it("loads portfolio stress fixture files", async () => {
    const dir = mkdtempSync(join(tmpdir(), "mosaic-mirofish-cli-"));
    const file = join(dir, "fixture.json");
    try {
      writeFileSync(
        file,
        JSON.stringify({
          current_positions: [
            {
              ticker: "688981.SH",
              market_price: 58,
              current_weight: 0.03,
            },
          ],
          sector_exposure: { semiconductor: 0.03 },
          theme_exposure: { localization: 0.03 },
        }),
      );

      const inputs = await loadMirofishPortfolioInputs({ currentPositionsFile: file });

      expect(inputs.current_positions?.[0]?.ticker).toBe("688981.SH");
      expect(inputs.sector_exposure).toEqual({ semiconductor: 0.03 });
      expect(inputs.theme_exposure).toEqual({ localization: 0.03 });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("accepts inline portfolio fixture objects and lets explicit exposure flags override", async () => {
    const inputs = await loadMirofishPortfolioInputs({
      currentPositionsJson: JSON.stringify({
        current_positions: [
          {
            ticker: "600519.SH",
            market_price: 1700,
            current_weight: 0.08,
          },
        ],
        sector_exposure: { consumer: 0.08 },
        theme_exposure: { premium_consumption: 0.08 },
      }),
      sectorExposureJson: JSON.stringify({ override_sector: 0.12 }),
    });

    expect(inputs.current_positions?.[0]?.ticker).toBe("600519.SH");
    expect(inputs.sector_exposure).toEqual({ override_sector: 0.12 });
    expect(inputs.theme_exposure).toEqual({ premium_consumption: 0.08 });
  });

  it("rejects malformed fixture values before calling the bridge", async () => {
    await expect(
      loadMirofishPortfolioInputs({
        currentPositionsJson: JSON.stringify([{ ticker: "600519.SH", market_price: "1700" }]),
      }),
    ).rejects.toThrow(/market_price must be a positive number/);
    await expect(
      loadMirofishPortfolioInputs({
        currentPositionsJson: JSON.stringify([{ ticker: "600519.SH", current_weight: 0.08 }]),
      }),
    ).rejects.toThrow(/market_price must be a positive number/);
  });
});

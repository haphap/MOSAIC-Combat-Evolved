import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  assertDailyCyclePromptSourceMode,
  loadCurrentPositionsFixture,
  nonProductionSourceGapBypass,
  resolveDailyCycleCohort,
  validateStructuredSmokeFixtureBundle,
} from "../src/cli/commands/daily-cycle.js";

function fixturePosition(ticker = "600519.SH") {
  return {
    ticker,
    sector: ticker === "600519.SH" ? "consumer" : "semiconductor",
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

function canonicalHash(value: unknown): string {
  const sort = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(sort);
    if (item === null || typeof item !== "object") return item;
    const record = item as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(record)
        .sort()
        .map((key) => [key, sort(record[key])]),
    );
  };
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(sort(value)))
    .digest("hex")}`;
}

function writeStructuredSmokeBundle(root: string, asOfDate = "2026-07-17") {
  for (const directory of [
    "economic_calendar",
    "geopolitical_events",
    "macro_snapshots",
    "market_breadth",
    "outcome_runtime",
    "runtime_snapshots",
    "sector_snapshots",
  ]) {
    mkdirSync(join(root, directory), { recursive: true });
  }
  const manifestPath = join(root, "geopolitical_events", "manifest.json");
  const manifestHash = canonicalHash({ source: "synthetic" });
  const manifestContent = JSON.stringify({ manifest_hash: manifestHash });
  writeFileSync(manifestPath, manifestContent);
  const macroPath = join(root, "macro_snapshots", asOfDate, "china.json");
  mkdirSync(join(root, "macro_snapshots", asOfDate), { recursive: true });
  const macroContent = JSON.stringify({ fixture: "synthetic", as_of_date: asOfDate });
  writeFileSync(macroPath, macroContent);
  const outcomeRuntimePath = join(root, "outcome_runtime", asOfDate, "event_coverage.json");
  mkdirSync(join(root, "outcome_runtime", asOfDate), { recursive: true });
  const outcomeRuntimeContent = JSON.stringify({ fixture: "synthetic", as_of_date: asOfDate });
  writeFileSync(outcomeRuntimePath, outcomeRuntimeContent);
  const artifactInventory = [
    {
      relative_path: "geopolitical_events/manifest.json",
      content_sha256: contentHash(manifestContent),
    },
    {
      relative_path: `macro_snapshots/${asOfDate}/china.json`,
      content_sha256: contentHash(macroContent),
    },
    {
      relative_path: `outcome_runtime/${asOfDate}/event_coverage.json`,
      content_sha256: contentHash(outcomeRuntimeContent),
    },
  ];
  const body = {
    schema_version: "structured_smoke_fixture_bundle_v1",
    as_of_date: asOfDate,
    fixture_class: "SYNTHETIC_NON_PRODUCTION",
    contains_vendor_prose: false,
    cache_root: root,
    geopolitical_manifest: manifestPath,
    geopolitical_manifest_hash: manifestHash,
    artifact_inventory: artifactInventory,
    artifact_inventory_hash: canonicalHash(artifactInventory),
  };
  const marker = { ...body, bundle_hash: canonicalHash(body) };
  const markerPath = join(root, "structured_smoke_fixture_bundle.json");
  writeFileSync(markerPath, JSON.stringify(marker));
  return { macroContent, macroPath, manifestPath, marker, markerPath };
}

function contentHash(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

describe("daily-cycle current-position fixture options", () => {
  it("allows direct prompt roots only in non-production smoke mode", () => {
    expect(() =>
      assertDailyCyclePromptSourceMode({ promptsRoot: "/tmp/reviewed-prompts" }, false),
    ).toThrow(/live execution forbids --prompts-root/);
    expect(() =>
      assertDailyCyclePromptSourceMode({ promptsRoot: "/tmp/reviewed-prompts" }, true),
    ).not.toThrow();
    expect(() => assertDailyCyclePromptSourceMode({}, false)).not.toThrow();
  });

  it("uses marked synthetic source fixtures for both smoke modes only", () => {
    expect(nonProductionSourceGapBypass({ fakeLlm: true })).toBe("structured_smoke");
    expect(nonProductionSourceGapBypass({ structuredSmoke: true })).toBe("structured_smoke");
    expect(nonProductionSourceGapBypass({})).toBeUndefined();
  });

  it("uses the canonical default cohort instead of the bridge config alias", () => {
    expect(resolveDailyCycleCohort({}, { active_cohort: "euphoria_2021" })).toBe("cohort_default");
    expect(
      resolveDailyCycleCohort(
        { cohort: "cohort_euphoria_2021" },
        { active_cohort: "euphoria_2021" },
      ),
    ).toBe("cohort_euphoria_2021");
  });

  it("rejects legacy aliases and unknown daily-cycle cohort ids", () => {
    expect(() =>
      resolveDailyCycleCohort({ cohort: "euphoria_2021" }, { active_cohort: "cohort_default" }),
    ).toThrow(/unknown daily-cycle cohort/);
    expect(() =>
      resolveDailyCycleCohort({ cohort: "cohort_unknown" }, { active_cohort: "cohort_default" }),
    ).toThrow(/unknown daily-cycle cohort/);
  });

  it("accepts only an exact hash-bound structured-smoke fixture bundle", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-structured-smoke-"));
    try {
      const fixture = writeStructuredSmokeBundle(root);
      expect(
        validateStructuredSmokeFixtureBundle("2026-07-17", {
          MOSAIC_CACHE_DIR: root,
          MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: fixture.manifestPath,
          MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH: fixture.marker.bundle_hash,
        }),
      ).toEqual({ bundleHash: fixture.marker.bundle_hash, markerPath: fixture.markerPath });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails closed when the synthetic fixture marker is missing or tampered", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-structured-smoke-"));
    try {
      expect(() =>
        validateStructuredSmokeFixtureBundle("2026-07-17", {
          MOSAIC_CACHE_DIR: root,
          MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: join(root, "missing.json"),
          MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH: `sha256:${"0".repeat(64)}`,
        }),
      ).toThrow(/marker or geopolitical manifest is unavailable/);

      const fixture = writeStructuredSmokeBundle(root);
      writeFileSync(
        fixture.markerPath,
        JSON.stringify({ ...fixture.marker, bundle_hash: `sha256:${"0".repeat(64)}` }),
      );
      expect(() =>
        validateStructuredSmokeFixtureBundle("2026-07-17", {
          MOSAIC_CACHE_DIR: root,
          MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: fixture.manifestPath,
          MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH: fixture.marker.bundle_hash,
        }),
      ).toThrow(/marker binding mismatch/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("rejects a valid fixture bundle for a different as-of date", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-structured-smoke-"));
    try {
      const fixture = writeStructuredSmokeBundle(root, "2026-07-16");
      expect(() =>
        validateStructuredSmokeFixtureBundle("2026-07-17", {
          MOSAIC_CACHE_DIR: root,
          MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: fixture.manifestPath,
          MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH: fixture.marker.bundle_hash,
        }),
      ).toThrow(/marker binding mismatch/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("rejects tampered, extra, and missing synthetic fixture artifacts", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-structured-smoke-"));
    try {
      const fixture = writeStructuredSmokeBundle(root);
      const env = {
        MOSAIC_CACHE_DIR: root,
        MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: fixture.manifestPath,
        MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH: fixture.marker.bundle_hash,
      };

      writeFileSync(fixture.macroPath, JSON.stringify({ fixture: "tampered" }));
      expect(() => validateStructuredSmokeFixtureBundle("2026-07-17", env)).toThrow(
        /artifact inventory mismatch/,
      );

      writeFileSync(fixture.macroPath, fixture.macroContent);
      const extraPath = join(root, "sector_snapshots", "extra.json");
      writeFileSync(extraPath, "{}");
      expect(() => validateStructuredSmokeFixtureBundle("2026-07-17", env)).toThrow(
        /artifact inventory mismatch/,
      );

      unlinkSync(extraPath);
      unlinkSync(fixture.macroPath);
      expect(() => validateStructuredSmokeFixtureBundle("2026-07-17", env)).toThrow(
        /artifact inventory mismatch/,
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("requires the caller to bind the expected synthetic fixture hash", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-structured-smoke-"));
    try {
      const fixture = writeStructuredSmokeBundle(root);
      expect(() =>
        validateStructuredSmokeFixtureBundle("2026-07-17", {
          MOSAIC_CACHE_DIR: root,
          MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: fixture.manifestPath,
        }),
      ).toThrow(/fixture bundle hash bindings/);
      expect(() =>
        validateStructuredSmokeFixtureBundle("2026-07-17", {
          MOSAIC_CACHE_DIR: root,
          MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: fixture.manifestPath,
          MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH: `sha256:${"f".repeat(64)}`,
        }),
      ).toThrow(/marker binding mismatch/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("rejects a symlinked synthetic fixture marker", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-structured-smoke-"));
    try {
      const fixture = writeStructuredSmokeBundle(root);
      const markerCopy = join(root, "marker-copy.json");
      writeFileSync(markerCopy, JSON.stringify(fixture.marker));
      unlinkSync(fixture.markerPath);
      symlinkSync("marker-copy.json", fixture.markerPath);

      expect(() =>
        validateStructuredSmokeFixtureBundle("2026-07-17", {
          MOSAIC_CACHE_DIR: root,
          MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST: fixture.manifestPath,
          MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH: fixture.marker.bundle_hash,
        }),
      ).toThrow(/marker or geopolitical manifest is unavailable/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("parses inline current positions JSON", () => {
    const snapshot = loadCurrentPositionsFixture({
      currentPositionsJson: JSON.stringify([fixturePosition()]),
    });

    expect(snapshot?.snapshot_status).toBe("loaded");
    expect(snapshot?.position_source).toBe("cli_fixture");
    expect(snapshot?.positions[0]?.ticker).toBe("600519.SH");
    expect(snapshot?.positions[0]?.sector).toBe("consumer");
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

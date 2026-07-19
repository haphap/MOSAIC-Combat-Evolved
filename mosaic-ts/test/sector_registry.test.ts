import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { STANDARD_SECTOR_ROLE_CONTRACTS } from "../src/agents/sector/_contracts.js";
import {
  CORE_SECTOR_COMPARISON_CRITERIA,
  COVERAGE_GATED_SECTOR_COMPARISON_CRITERIA,
  OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA,
  SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION,
} from "../src/agents/sector/comparison.js";
import {
  buildSectorUniverseManifest,
  SECTOR_DIRECTION_COMPARISON_CONTRACT,
  SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT,
  SECTOR_DIRECTION_METRIC_REGISTRY,
  SECTOR_DIRECTION_REGISTRY,
  SECTOR_OVERLAP_PRECEDENCE,
  SectorUniverseManifestSchema,
} from "../src/agents/sector/registry.js";

describe("closed SW2021 Sector universe registry", () => {
  const manifest = SectorUniverseManifestSchema.parse(buildSectorUniverseManifest());

  it("is the unique source for nine roles, 47 directions, 64 codes, and 26 metrics", () => {
    expect(SECTOR_OVERLAP_PRECEDENCE).toHaveLength(9);
    expect(manifest.direction_contracts).toHaveLength(47);
    expect(SECTOR_DIRECTION_METRIC_REGISTRY).toHaveLength(26);
    const codes = new Set<string>();
    for (const entry of Object.values(SECTOR_DIRECTION_REGISTRY)) {
      for (const row of entry.universe) codes.add(row.code);
      for (const direction of entry.directions) {
        for (const row of direction.included) codes.add(row.code);
      }
    }
    expect(codes.size).toBe(64);
  });

  it.each(SECTOR_OVERLAP_PRECEDENCE)("%s role contract is derived from the registry", (agent) => {
    expect(STANDARD_SECTOR_ROLE_CONTRACTS[agent].directionIds).toEqual(
      SECTOR_DIRECTION_REGISTRY[agent].directions.map((row) => row.directionId),
    );
  });

  it("queries both historical and current membership branches for every code", () => {
    for (const plan of manifest.membership_query_plans) {
      const keys = new Set(
        plan.branches.map(
          (branch) => `${branch.parameter}:${branch.classification_code}:${branch.is_new}`,
        ),
      );
      const codes = new Set(
        plan.branches.map((branch) => `${branch.parameter}:${branch.classification_code}`),
      );
      for (const code of codes) {
        expect(keys).toContain(`${code}:Y`);
        expect(keys).toContain(`${code}:N`);
      }
    }
  });

  it("fully partitions every parent universe into at least three non-overlapping directions", () => {
    for (const entry of Object.values(SECTOR_DIRECTION_REGISTRY)) {
      expect(entry.directions.length).toBeGreaterThanOrEqual(3);
      const universe = entry.universe.map((row) => `${row.level}:${row.code}`).sort();
      const partition = entry.directions
        .flatMap((direction) => direction.included)
        .map((row) => `${row.level}:${row.code}`)
        .sort();
      expect(new Set(partition).size).toBe(partition.length);
      expect(partition).toEqual(universe);
    }
  });

  it("keeps ETF metrics optional and all constituent metrics required", () => {
    expect(
      SECTOR_DIRECTION_METRIC_REGISTRY.filter((row) => row.metric_family === "ETF_CONFIRMATION"),
    ).toHaveLength(13);
    expect(
      SECTOR_DIRECTION_METRIC_REGISTRY.filter(
        (row) => row.metric_family === "ETF_CONFIRMATION",
      ).every((row) => !row.required_for_direction_readiness && row.minimum_coverage_ratio === 0.8),
    ).toBe(true);
    expect(
      SECTOR_DIRECTION_METRIC_REGISTRY.filter(
        (row) => row.metric_family !== "ETF_CONFIRMATION",
      ).every((row) => row.required_for_direction_readiness && row.minimum_coverage_ratio === 0.9),
    ).toBe(true);
  });

  it("drives immutable comparison semantics from the registered contract", () => {
    expect(SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION).toBe(
      SECTOR_DIRECTION_COMPARISON_CONTRACT.comparison_contract_version,
    );
    expect(CORE_SECTOR_COMPARISON_CRITERIA).toBe(
      SECTOR_DIRECTION_COMPARISON_CONTRACT.core_criteria,
    );
    expect(COVERAGE_GATED_SECTOR_COMPARISON_CRITERIA).toBe(
      SECTOR_DIRECTION_COMPARISON_CONTRACT.coverage_gated_criteria,
    );
    expect(OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA).toBe(
      SECTOR_DIRECTION_COMPARISON_CONTRACT.optional_etf_criteria,
    );
    expect(Object.isFrozen(SECTOR_DIRECTION_COMPARISON_CONTRACT)).toBe(true);
    expect(Object.isFrozen(SECTOR_DIRECTION_COMPARISON_CONTRACT.core_criteria)).toBe(true);
    expect(manifest.direction_conflict_resolver_contract).toEqual(
      SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT,
    );
    expect(SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.review_round_limit).toBe(1);
    expect(SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.acceptance_rule).toBe(
      "UNIQUE_CONDORCET_WINNER_AND_UNIQUE_CONDORCET_LOSER",
    );
    expect(Object.isFrozen(SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT)).toBe(true);
    expect(Object.isFrozen(SECTOR_DIRECTION_REGISTRY)).toBe(true);
    expect(Object.isFrozen(SECTOR_DIRECTION_METRIC_REGISTRY)).toBe(true);
  });

  it("rejects nested contract extensions and rehashed semantic drift", () => {
    const extended = structuredClone(buildSectorUniverseManifest()) as unknown as Record<
      string,
      unknown
    >;
    const extendedScoring = extended.security_scoring_contract as Record<string, unknown>;
    extendedScoring.unregistered_override = true;
    expect(SectorUniverseManifestSchema.safeParse(extended).success).toBe(false);

    const drifted = structuredClone(buildSectorUniverseManifest()) as unknown as Record<
      string,
      unknown
    >;
    const metrics = drifted.direction_metric_registry as Array<Record<string, unknown>>;
    const firstMetric = metrics[0];
    if (!firstMetric) throw new Error("generated manifest must contain metrics");
    firstMetric.formula_id = "UNREGISTERED_REHASHED_FORMULA";
    const metricBody = withoutKey(firstMetric, "metric_contract_hash");
    firstMetric.metric_contract_hash = canonicalHash(metricBody);
    drifted.direction_metric_registry_hash = canonicalHash(metrics);
    drifted.manifest_hash = canonicalHash(withoutKey(drifted, "manifest_hash"));
    expect(SectorUniverseManifestSchema.safeParse(drifted).success).toBe(false);
  });
});

function withoutKey(value: Record<string, unknown>, omitted: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => key !== omitted));
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value;
}

import { describe, expect, it } from "vitest";
import { STANDARD_SECTOR_ROLE_CONTRACTS } from "../src/agents/sector/_contracts.js";
import {
  buildSectorUniverseManifest,
  SECTOR_DIRECTION_METRIC_REGISTRY,
  SECTOR_DIRECTION_REGISTRY,
  SECTOR_OVERLAP_PRECEDENCE,
  SectorUniverseManifestSchema,
} from "../src/agents/sector/registry.js";

describe("closed SW2021 Sector universe registry", () => {
  const manifest = SectorUniverseManifestSchema.parse(buildSectorUniverseManifest());

  it("is the unique source for nine roles, 37 directions, 44 codes, and 26 metrics", () => {
    expect(SECTOR_OVERLAP_PRECEDENCE).toHaveLength(9);
    expect(manifest.direction_contracts).toHaveLength(37);
    expect(SECTOR_DIRECTION_METRIC_REGISTRY).toHaveLength(26);
    const codes = new Set<string>();
    for (const entry of Object.values(SECTOR_DIRECTION_REGISTRY)) {
      for (const row of entry.universe) codes.add(row.code);
      if ("universeExcluded" in entry) {
        for (const row of entry.universeExcluded) codes.add(row.code);
      }
      for (const direction of entry.directions) {
        for (const row of direction.included) codes.add(row.code);
        if ("excluded" in direction) {
          for (const row of direction.excluded ?? []) codes.add(row.code);
        }
      }
    }
    expect(codes.size).toBe(44);
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

  it("binds a registered null only for single-direction roles", () => {
    for (const contract of manifest.direction_contracts) {
      const directionCount =
        STANDARD_SECTOR_ROLE_CONTRACTS[
          contract.sector_agent_id as keyof typeof STANDARD_SECTOR_ROLE_CONTRACTS
        ].directionIds.length;
      expect(contract.single_direction_null_benchmark_contract_id === null).toBe(
        directionCount !== 1,
      );
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
});

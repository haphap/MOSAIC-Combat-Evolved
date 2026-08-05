import { afterEach, describe, expect, it, vi } from "vitest";

const RELEASE_MODULE = "../src/autoresearch/execution_behavior_release.js";
const SECTOR_DIRECTIVE_MODULE = "../src/agents/sector/phase_directives.js";
const REPAIR_DIRECTIVE_MODULE = "../src/agents/helpers/structured_repair_directives.js";

interface ReleaseContract {
  agent_id: string;
  language: "en" | "zh";
  execution_behavior_version: string;
  structured_output_schema_bindings: Array<{
    phase: string;
    immutable_phase_instruction_hash: string;
  }>;
}

interface ReleaseManifest {
  execution_behavior_release_id: string;
  execution_contracts: ReleaseContract[];
}

afterEach(() => {
  vi.doUnmock(SECTOR_DIRECTIVE_MODULE);
  vi.doUnmock(REPAIR_DIRECTIVE_MODULE);
  vi.resetModules();
});

describe("execution behavior canonical directive binding", () => {
  it("changes the release id and Sector version when a runtime phase directive changes", async () => {
    const baselineModule = await import(RELEASE_MODULE);
    const baseline = baselineModule.buildExecutionBehaviorReleaseManifest(releaseInput());
    const actualDirectives = await import(SECTOR_DIRECTIVE_MODULE);

    vi.resetModules();
    vi.doMock(SECTOR_DIRECTIVE_MODULE, () => ({
      ...actualDirectives,
      canonicalSectorPhaseDirectiveBundle: (
        input: Parameters<typeof actualDirectives.canonicalSectorPhaseDirectiveBundle>[0],
      ) => {
        const bundle = actualDirectives.canonicalSectorPhaseDirectiveBundle(input);
        return {
          ...bundle,
          primary_system_message_template: `${bundle.primary_system_message_template}\nDIRECTIVE_MUTATION`,
        };
      },
    }));
    const mutatedModule = await import(RELEASE_MODULE);
    const mutated = mutatedModule.buildExecutionBehaviorReleaseManifest(releaseInput());

    const baselineEnergy = contractFor(baseline, "energy", "zh");
    const mutatedEnergy = contractFor(mutated, "energy", "zh");
    expect(
      mutatedEnergy.structured_output_schema_bindings[0]?.immutable_phase_instruction_hash,
    ).not.toBe(
      baselineEnergy.structured_output_schema_bindings[0]?.immutable_phase_instruction_hash,
    );
    expect(mutatedEnergy.execution_behavior_version).not.toBe(
      baselineEnergy.execution_behavior_version,
    );
    expect(mutated.execution_behavior_release_id).not.toBe(baseline.execution_behavior_release_id);
    expect(contractFor(mutated, "china", "zh")).toEqual(contractFor(baseline, "china", "zh"));
  });

  it("changes the release id and versions when the shared repair directive changes", async () => {
    const baselineModule = await import(RELEASE_MODULE);
    const baseline = baselineModule.buildExecutionBehaviorReleaseManifest(releaseInput());
    const actualRepairs = await import(REPAIR_DIRECTIVE_MODULE);

    vi.resetModules();
    vi.doMock(REPAIR_DIRECTIVE_MODULE, () => ({
      ...actualRepairs,
      canonicalStructuredRepairDirectiveManifest: () => {
        const directives = actualRepairs.canonicalStructuredRepairDirectiveManifest();
        const first = directives[0];
        if (!first) throw new Error("repair directive fixture is empty");
        return [
          { ...first, system_message: `${first.system_message} DIRECTIVE_MUTATION` },
          ...directives.slice(1),
        ];
      },
    }));
    const mutatedModule = await import(RELEASE_MODULE);
    const mutated = mutatedModule.buildExecutionBehaviorReleaseManifest(releaseInput());

    const baselineChina = contractFor(baseline, "china", "en");
    const mutatedChina = contractFor(mutated, "china", "en");
    expect(
      mutatedChina.structured_output_schema_bindings[0]?.immutable_phase_instruction_hash,
    ).not.toBe(
      baselineChina.structured_output_schema_bindings[0]?.immutable_phase_instruction_hash,
    );
    expect(mutatedChina.execution_behavior_version).not.toBe(
      baselineChina.execution_behavior_version,
    );
    expect(mutated.execution_behavior_release_id).not.toBe(baseline.execution_behavior_release_id);
  });
});

function releaseInput() {
  return {
    provider: "anthropic",
    model: "claude-sonnet-4",
    baseUrlMode: "PROVIDER_DEFAULT" as const,
  };
}

function contractFor(
  manifest: ReleaseManifest,
  agent: string,
  language: "en" | "zh",
): ReleaseContract {
  const contract = manifest.execution_contracts.find(
    (candidate) => candidate.agent_id === agent && candidate.language === language,
  );
  if (!contract) throw new Error(`${agent}:${language} execution contract is missing`);
  return contract;
}

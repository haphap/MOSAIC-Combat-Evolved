import { describe, expect, it } from "vitest";
import {
  buildRuntimeAgentManifestArtifact,
  CANONICAL_L4_STAGE_SEQUENCE,
  RUNTIME_AGENT_SPECS,
  RUNTIME_AGENT_STAGE_SPEC_BY_KEY,
  renderRuntimeAgentManifestArtifact,
  runtimeAgentStageKey,
  validateRuntimeAgentManifestArtifact,
} from "../src/agents/prompts/runtime_agent_spec.js";

describe("stage-aware runtime agent manifest", () => {
  it("covers all runtime agents and the canonical L4 invocation stages", () => {
    const artifact = buildRuntimeAgentManifestArtifact();

    expect(artifact.runtime_agent_count).toBe(25);
    expect(artifact.runtime_stage_count).toBe(26);
    expect(artifact.canonical_l4_sequence).toEqual(CANONICAL_L4_STAGE_SEQUENCE);
    expect(validateRuntimeAgentManifestArtifact(artifact)).toEqual([]);
    expect(
      artifact.agents
        .flatMap((agent) => agent.stages)
        .every((stage) => stage.enablement === "enabled"),
    ).toBe(true);
  });

  it("declares CIO proposal and final as separate stage contracts", () => {
    const proposal = RUNTIME_AGENT_STAGE_SPEC_BY_KEY.get(
      runtimeAgentStageKey("cio", "cio_proposal"),
    );
    const final = RUNTIME_AGENT_STAGE_SPEC_BY_KEY.get(runtimeAgentStageKey("cio", "cio_final"));

    expect(proposal?.requiredSourceIds).not.toContain("candidate_target_state");
    expect(proposal?.producedSourceIds).toEqual([
      "candidate_target_state",
      "position_review_state",
    ]);
    expect(final?.requiredSourceIds).toEqual(
      expect.arrayContaining([
        "candidate_target_state",
        "cro_review_state",
        "execution_feasibility_state",
      ]),
    );
    expect(proposal?.outputSchemaRef).not.toBe(final?.outputSchemaRef);
    for (const key of [
      ["alpha_discovery", "alpha_discovery"],
      ["cio", "cio_proposal"],
      ["cro", "cro_review"],
      ["autonomous_execution", "execution_feasibility"],
      ["cio", "cio_final"],
    ] as const) {
      expect(
        RUNTIME_AGENT_STAGE_SPEC_BY_KEY.get(runtimeAgentStageKey(key[0], key[1]))?.enablement,
      ).toBe("enabled");
    }
  });

  it("registers a deterministic fallback factory for every stage", () => {
    for (const spec of RUNTIME_AGENT_SPECS) {
      for (const stage of spec.stages) {
        expect(stage.fallbackFactoryId).toBe(`${spec.promptIrAgentId}.${stage.stage}.fallback`);
        expect(stage.fallbackFactoryVersion).toBe("1");
      }
    }
  });

  it("renders deterministic JSON", () => {
    const artifact = buildRuntimeAgentManifestArtifact();
    expect(JSON.parse(renderRuntimeAgentManifestArtifact(artifact))).toEqual(artifact);
  });
});

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
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

    expect(artifact.runtime_agent_count).toBe(28);
    expect(artifact.runtime_stage_count).toBe(29);
    expect(artifact.default_cohort).toBe("cohort_default");
    expect(artifact.private_knot_cohort_enablement.map((row) => row.cohort)).toEqual([
      "cohort_bull_2007",
      "cohort_bull_2016",
      "cohort_crisis_2008",
      "cohort_crisis_covid",
      "cohort_default",
      "cohort_euphoria_2021",
      "cohort_rate_tightening",
      "cohort_recovery_2020",
    ]);
    for (const cohort of artifact.private_knot_cohort_enablement) {
      expect(cohort.enabled_agent_stages).toHaveLength(29);
      expect(cohort.bundled_fallback_agent_stages).toEqual([]);
    }
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
    expect(proposal?.outputSchemaFields).toEqual([
      "agent_id",
      "decision_stage",
      "decision_disposition",
      "target_positions",
      "cash_weight",
      "decision_reason",
      "confidence",
      "claims",
      "claim_refs",
      "macro_input_attributions",
    ]);
    expect(proposal?.outputSchemaFields).not.toContain("cro_control_resolutions");
    expect(proposal?.outputSchemaFields).not.toContain("execution_control_resolutions");
    expect(final?.outputSchemaFields).toEqual([
      "agent_id",
      "decision_stage",
      "decision_disposition",
      "target_positions",
      "cash_weight",
      "decision_reason",
      "cro_control_resolutions",
      "execution_control_resolutions",
      "confidence",
      "claims",
      "claim_refs",
      "macro_input_attributions",
    ]);
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

  it("registers exactly three structured repair attempts and no fallback factory", () => {
    for (const spec of RUNTIME_AGENT_SPECS) {
      for (const stage of spec.stages) {
        expect(stage.maxRepairAttempts).toBe(3);
        expect(stage).not.toHaveProperty("fallbackFactoryId");
      }
    }
  });

  it("records exact output fields on every runtime stage", () => {
    const artifact = buildRuntimeAgentManifestArtifact();
    for (const agent of artifact.agents) {
      const runtime = RUNTIME_AGENT_SPECS.find((spec) => spec.agent === agent.agent);
      expect(runtime).toBeTruthy();
      for (const stage of agent.stages) {
        const expected = runtime?.stages.find((row) => row.stage === stage.stage);
        expect(stage.output_schema_fields).toEqual(expected?.outputSchemaFields);
      }
    }
  });

  it("renders deterministic JSON", () => {
    const artifact = buildRuntimeAgentManifestArtifact();
    expect(JSON.parse(renderRuntimeAgentManifestArtifact(artifact))).toEqual(artifact);
  });

  it("keeps the committed cross-language roster manifest in sync", () => {
    const artifact = buildRuntimeAgentManifestArtifact();
    const committed = JSON.parse(
      readFileSync(
        join(process.cwd(), "..", "registry", "prompt_checks", "runtime_agent_manifest_v4.json"),
        "utf-8",
      ),
    );
    const grouped = Object.fromEntries(
      Object.keys(AGENTS_BY_LAYER).map((layer) => [
        layer,
        artifact.agents.filter((agent) => agent.layer === layer).map((agent) => agent.agent),
      ]),
    );

    expect(committed).toEqual(artifact);
    expect(grouped).toEqual(AGENTS_BY_LAYER);
  });
});

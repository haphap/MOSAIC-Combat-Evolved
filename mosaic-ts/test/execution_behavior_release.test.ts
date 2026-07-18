import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  MACRO_AGENT_IDS,
  MACRO_PROMPT_COHORT_IDS,
  renderMacroPromptBody,
} from "../src/agents/macro/_contracts.js";
import { renderBundledPrompt } from "../src/agents/prompts/bundled_prompt_renderer.js";
import {
  extractCohortBehavior,
  replaceCohortBehavior,
} from "../src/agents/prompts/cohort_behavior.js";
import { ALL_AGENTS, promptPath } from "../src/agents/prompts/cohorts.js";
import { upsertRuntimeEvidenceContract } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "../src/agents/prompts/runtime_agent_spec.js";
import {
  buildExecutionBehaviorReleaseManifest,
  loadExecutionBehaviorReleaseManifest,
  releaseVariantFor,
  validateExecutionBehaviorReleaseManifest,
} from "../src/autoresearch/execution_behavior_release.js";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots) rmSync(root, { recursive: true, force: true });
  roots.length = 0;
});

describe("execution behavior release", () => {
  it("validates the committed atomic release", () => {
    const release = loadExecutionBehaviorReleaseManifest(
      resolve(
        process.cwd(),
        "..",
        "registry",
        "prompt_checks",
        "execution_behavior_release_manifest_v1.json",
      ),
    );
    expect(release.active_production_variants).toHaveLength(16);
    expect(release.variants).toHaveLength(448);
    const roleManifest = JSON.parse(
      readFileSync(
        resolve(
          process.cwd(),
          "..",
          "registry",
          "prompt_checks",
          "agent_prompt_role_contract_manifest_v2.json",
        ),
        "utf8",
      ),
    ) as {
      private_prompt_commit: string;
      execution_behavior_release_id: string;
      execution_behavior_release_hash: string;
    };
    expect(release.private_prompt_commit).toBe(roleManifest.private_prompt_commit);
    expect(release.execution_behavior_release_id).toBe(roleManifest.execution_behavior_release_id);
    expect(release.execution_behavior_release_hash).toBe(
      roleManifest.execution_behavior_release_hash,
    );
  });

  it("atomically binds all 448 prompt variants and 16 production rosters", () => {
    const fixture = promptFixture();
    const manifest = buildExecutionBehaviorReleaseManifest({
      ...fixture,
      privatePromptCommit: "a".repeat(40),
      provider: "anthropic",
      model: "claude-sonnet-4",
      baseUrlMode: "PROVIDER_DEFAULT",
    });

    expect(manifest.active_production_variants).toHaveLength(16);
    expect(manifest.variants).toHaveLength(448);
    expect(new Set(manifest.variants.map((variant) => variant.variant_path)).size).toBe(448);
    expect(
      manifest.variants.every((variant) =>
        /^sha256:[0-9a-f]{64}$/.test(variant.structured_provider_contract_hash),
      ),
    ).toBe(true);
    expect(
      releaseVariantFor(
        manifest,
        "cohort_default",
        "zh",
        "energy",
      ).structured_output_schema_bindings.map((binding) => binding.phase),
    ).toEqual(["DIRECTION_RESEARCH", "CONFLICT_REVIEW", "FINAL_SELECTION"]);
    expect(
      releaseVariantFor(
        manifest,
        "cohort_default",
        "en",
        "cio",
      ).structured_output_schema_bindings.map((binding) => binding.phase),
    ).toEqual(["CIO_PROPOSAL", "CIO_FINAL"]);
    expect(
      releaseVariantFor(manifest, "cohort_default", "zh", "china")
        .structured_output_schema_bindings,
    ).toHaveLength(1);
    expect(
      releaseVariantFor(manifest, "cohort_default", "zh", "china").execution_behavior_version,
    ).not.toBe(
      releaseVariantFor(manifest, "cohort_default", "en", "china").execution_behavior_version,
    );
    expect(
      releaseVariantFor(manifest, "cohort_default", "zh", "china").execution_behavior_version,
    ).toBe(
      releaseVariantFor(manifest, "cohort_bull_2007", "zh", "china").execution_behavior_version,
    );
    expect(validateExecutionBehaviorReleaseManifest(manifest)).toEqual(manifest);
  });

  it("accepts a private cohort-behavior mutation without changing execution behavior", () => {
    const fixture = promptFixture();
    const baseline = buildExecutionBehaviorReleaseManifest({
      ...fixture,
      privatePromptCommit: "c".repeat(40),
      provider: "anthropic",
      model: "claude-sonnet-4",
      baseUrlMode: "PROVIDER_DEFAULT",
    });
    const path = promptPath({
      agent: "china",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fixture.privatePromptsRoot,
    });
    const original = readFileSync(path, "utf8");
    writeFileSync(
      path,
      replaceCohortBehavior(
        original,
        `${extractCohortBehavior(original)} 先检查最强反证，再形成结论。`,
      ),
    );
    const candidate = buildExecutionBehaviorReleaseManifest({
      ...fixture,
      privatePromptCommit: "d".repeat(40),
      provider: "anthropic",
      model: "claude-sonnet-4",
      baseUrlMode: "PROVIDER_DEFAULT",
    });
    const before = releaseVariantFor(baseline, "cohort_default", "zh", "china");
    const after = releaseVariantFor(candidate, "cohort_default", "zh", "china");
    expect(after.prompt_behavior_version).not.toBe(before.prompt_behavior_version);
    expect(after.execution_behavior_version).toBe(before.execution_behavior_version);
    expect(after.immutable_contract_block_hash).toBe(before.immutable_contract_block_hash);
  });

  it("rejects prompt drift and manifest hash tampering", () => {
    const fixture = promptFixture();
    const path = promptPath({
      agent: "china",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fixture.privatePromptsRoot,
    });
    writeFileSync(path, `${readFileSync(path, "utf8")}\nresearch_knobs: leaked\n`);
    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...fixture,
        privatePromptCommit: "b".repeat(40),
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/not canonical|research knobs/);

    writeCanonicalPrompt(fixture.privatePromptsRoot, "china", "cohort_default", "zh");
    const manifest = buildExecutionBehaviorReleaseManifest({
      ...fixture,
      privatePromptCommit: "b".repeat(40),
      provider: "anthropic",
      model: "claude-sonnet-4",
      baseUrlMode: "PROVIDER_DEFAULT",
    });
    const tampered = structuredClone(manifest);
    const firstVariant = tampered.variants[0];
    if (!firstVariant) throw new Error("expected a release variant");
    firstVariant.prompt_content_hash = `sha256:${"0".repeat(64)}`;
    expect(() => validateExecutionBehaviorReleaseManifest(tampered)).toThrow();

    const providerTampered = structuredClone(manifest);
    const providerVariant = providerTampered.variants[0];
    if (!providerVariant) throw new Error("expected a release variant");
    providerVariant.structured_provider_contract_hash = `sha256:${"0".repeat(64)}`;
    expect(() => validateExecutionBehaviorReleaseManifest(providerTampered)).toThrow(
      /structured provider contract drift/,
    );
  });
});

function promptFixture(): { privatePromptsRoot: string; bundledPromptsRoot: string } {
  const root = mkdtempSync(join(tmpdir(), "mosaic-behavior-release-"));
  roots.push(root);
  const privatePromptsRoot = join(root, "private", "prompts", "mosaic");
  const bundledPromptsRoot = join(root, "bundled", "prompts", "mosaic");
  for (const cohort of MACRO_PROMPT_COHORT_IDS) {
    for (const language of ["en", "zh"] as const) {
      for (const agent of ALL_AGENTS) {
        writeCanonicalPrompt(privatePromptsRoot, agent, cohort, language);
      }
    }
  }
  for (const language of ["en", "zh"] as const) {
    for (const agent of ALL_AGENTS) {
      writeCanonicalPrompt(bundledPromptsRoot, agent, "cohort_default", language);
    }
  }
  return { privatePromptsRoot, bundledPromptsRoot };
}

function writeCanonicalPrompt(
  root: string,
  agent: string,
  cohort: string,
  language: "en" | "zh",
): void {
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
  if (!spec) throw new Error(`missing runtime spec ${agent}`);
  const body = MACRO_AGENT_IDS.includes(agent as (typeof MACRO_AGENT_IDS)[number])
    ? renderMacroPromptBody(
        agent as (typeof MACRO_AGENT_IDS)[number],
        language,
        cohort as (typeof MACRO_PROMPT_COHORT_IDS)[number],
      )
    : renderBundledPrompt(agent, language, cohort);
  const path = promptPath({
    agent,
    cohort,
    language,
    promptsRoot: root,
  });
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(
    path,
    upsertRuntimeEvidenceContract(body, spec, language, { includeResearchKnobDetails: false }),
  );
}

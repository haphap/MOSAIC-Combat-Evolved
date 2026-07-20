import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "../src/agents/prompts/runtime_agent_spec.js";
import { upsertRuntimeEvidenceContract } from "../src/agents/prompts/runtime_evidence_contract.js";
import {
  buildExecutionBehaviorReleaseManifest,
  executionBehaviorReleaseArchiveFilename,
  loadExecutionBehaviorReleaseManifest,
  releaseVariantFor,
  STRUCTURED_PROVIDER_CONTRACT_VERSION,
  validateExecutionBehaviorReleaseManifest,
  writeExecutionBehaviorReleaseArtifacts,
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
    expect(STRUCTURED_PROVIDER_CONTRACT_VERSION).toBe("structured_provider_contract_v2");
    expect(
      releaseVariantFor(manifest, "cohort_default", "zh", "china")
        .structured_provider_contract_hash,
    ).not.toBe(
      releaseVariantFor(manifest, "cohort_default", "zh", "geopolitical")
        .structured_provider_contract_hash,
    );
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
    fixture.privatePromptCommit = commitPrivatePrompts(fixture, "mutate cohort behavior");
    const candidate = buildExecutionBehaviorReleaseManifest({
      ...fixture,
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

  it("rejects a private prompt tree that does not match the attributed commit", () => {
    const fixture = promptFixture();
    const path = promptPath({
      agent: "china",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fixture.privatePromptsRoot,
    });
    writeFileSync(path, `${readFileSync(path, "utf8")}\nuncommitted change\n`);

    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...fixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow("prompt_source_tree_drift:private");
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
    fixture.privatePromptCommit = commitPrivatePrompts(fixture, "commit rejected prompt");
    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...fixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/not canonical|private KNOT/);

    writeCanonicalPrompt(fixture.privatePromptsRoot, "china", "cohort_default", "zh");
    fixture.privatePromptCommit = commitPrivatePrompts(fixture, "restore canonical prompt");
    const manifest = buildExecutionBehaviorReleaseManifest({
      ...fixture,
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

  it("rejects an English mutable behavior hidden inside a zh prompt", () => {
    const fixture = promptFixture();
    const path = promptPath({
      agent: "china",
      cohort: "cohort_bull_2007",
      language: "zh",
      promptsRoot: fixture.privatePromptsRoot,
    });
    writeFileSync(
      path,
      replaceCohortBehavior(readFileSync(path, "utf8"), "This block is English, not Chinese."),
    );
    fixture.privatePromptCommit = commitPrivatePrompts(fixture, "commit invalid zh behavior");

    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...fixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/Chinese cohort behavior must contain meaningful Chinese prose/);
  });

  it("rejects identical behavior across all eight cohorts", () => {
    const fixture = promptFixture();
    const defaultPath = promptPath({
      agent: "china",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fixture.privatePromptsRoot,
    });
    const behavior = extractCohortBehavior(readFileSync(defaultPath, "utf8"));
    for (const cohort of MACRO_PROMPT_COHORT_IDS) {
      const path = promptPath({
        agent: "china",
        cohort,
        language: "zh",
        promptsRoot: fixture.privatePromptsRoot,
      });
      writeFileSync(path, replaceCohortBehavior(readFileSync(path, "utf8"), behavior));
    }
    fixture.privatePromptCommit = commitPrivatePrompts(fixture, "commit identical cohorts");

    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...fixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/every production cohort must have distinct cohort behavior/);
  });

  it("rejects disguised private evolution policy content", () => {
    const fixture = promptFixture();
    const path = promptPath({
      agent: "china",
      cohort: "cohort_bull_2007",
      language: "en",
      promptsRoot: fixture.privatePromptsRoot,
    });
    writeFileSync(
      path,
      replaceCohortBehavior(
        readFileSync(path, "utf8"),
        "Use the Darwinian evolution state before interpreting evidence.",
      ),
    );
    fixture.privatePromptCommit = commitPrivatePrompts(fixture, "commit private policy leak");

    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...fixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/private KNOT policy must remain hidden/);
  });

  it("archives every immutable release before advancing the active pointer", () => {
    const fixture = promptFixture();
    const root = mkdtempSync(join(tmpdir(), "mosaic-behavior-archive-"));
    roots.push(root);
    const activeManifestPath = join(root, "active.json");
    const archiveRoot = join(root, "archive");
    const baseline = buildExecutionBehaviorReleaseManifest({
      ...fixture,
      provider: "anthropic",
      model: "claude-sonnet-4",
      baseUrlMode: "PROVIDER_DEFAULT",
    });
    git(fixture.privateRepoRoot, "commit", "--allow-empty", "-m", "advance private release");
    fixture.privatePromptCommit = git(fixture.privateRepoRoot, "rev-parse", "HEAD");
    const prepared = buildExecutionBehaviorReleaseManifest({
      ...fixture,
      provider: "anthropic",
      model: "claude-sonnet-4",
      baseUrlMode: "PROVIDER_DEFAULT",
    });

    writeExecutionBehaviorReleaseArtifacts({
      manifest: baseline,
      activeManifestPath,
      archiveRoot,
    });
    writeExecutionBehaviorReleaseArtifacts({
      manifest: prepared,
      activeManifestPath,
      archiveRoot,
    });

    expect(loadExecutionBehaviorReleaseManifest(activeManifestPath)).toEqual(prepared);
    expect(readdirSync(archiveRoot).sort()).toEqual(
      [
        executionBehaviorReleaseArchiveFilename(baseline),
        executionBehaviorReleaseArchiveFilename(prepared),
      ].sort(),
    );
    const baselineArchive = join(archiveRoot, executionBehaviorReleaseArchiveFilename(baseline));
    expect(JSON.parse(readFileSync(baselineArchive, "utf8"))).toEqual(baseline);

    writeFileSync(baselineArchive, "{}\n");
    expect(() =>
      writeExecutionBehaviorReleaseArtifacts({
        manifest: baseline,
        activeManifestPath,
        archiveRoot,
      }),
    ).toThrow(/immutable execution behavior release archive collision/);
    expect(loadExecutionBehaviorReleaseManifest(activeManifestPath)).toEqual(prepared);
  });
});

interface PromptFixture {
  privatePromptsRoot: string;
  bundledPromptsRoot: string;
  privateRepoRoot: string;
  privatePromptCommit: string;
}

function promptFixture(): PromptFixture {
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
  const privateRepoRoot = join(root, "private");
  git(privateRepoRoot, "init", "-b", "main");
  git(privateRepoRoot, "config", "user.name", "Test");
  git(privateRepoRoot, "config", "user.email", "test@example.com");
  const privatePromptCommit = commitPrivatePrompts(
    { privateRepoRoot, privatePromptsRoot },
    "seed private prompts",
  );
  return { privatePromptsRoot, bundledPromptsRoot, privateRepoRoot, privatePromptCommit };
}

function commitPrivatePrompts(
  fixture: Pick<PromptFixture, "privateRepoRoot" | "privatePromptsRoot">,
  message: string,
): string {
  git(fixture.privateRepoRoot, "add", "prompts/mosaic");
  git(fixture.privateRepoRoot, "commit", "-m", message);
  return git(fixture.privateRepoRoot, "rev-parse", "HEAD");
}

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-C", cwd, ...args], { encoding: "utf8" }).trim();
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
    ? renderMacroPromptBody(agent as (typeof MACRO_AGENT_IDS)[number], language, "cohort_default")
    : renderBundledPrompt(agent, language, "cohort_default");
  const baseline = upsertRuntimeEvidenceContract(body, spec, language);
  const cohortIndex = MACRO_PROMPT_COHORT_IDS.indexOf(
    cohort as (typeof MACRO_PROMPT_COHORT_IDS)[number],
  );
  const prompt =
    cohort === "cohort_default"
      ? baseline
      : replaceCohortBehavior(
          baseline,
          language === "zh"
            ? `这是仅用于验证发布契约的中文场景行为，场景编号为 ${cohortIndex}。`
            : `Opaque fixture behavior for scenario ${cohortIndex}.`,
        );
  const path = promptPath({
    agent,
    cohort,
    language,
    promptsRoot: root,
  });
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, prompt);
}

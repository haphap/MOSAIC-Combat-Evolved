import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
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
    const release = loadExecutionBehaviorReleaseManifest(committedExecutionReleasePath());
    expect(release.active_production_variants).toHaveLength(16);
    expect(release.execution_contracts).toHaveLength(56);
    expect(release.private_prompt_commit).toMatch(/^[0-9a-f]{40}$/);
    expect(release.execution_behavior_release_id).toMatch(
      /^execution-behavior-release:[0-9a-f]{64}$/,
    );
    expect(release.execution_behavior_release_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("validates all prompt variants while persisting only 56 execution contracts", () => {
    const fixture = promptFixture();
    const manifest = buildExecutionBehaviorReleaseManifest({
      ...fixture,
      provider: "anthropic",
      model: "claude-sonnet-4",
      baseUrlMode: "PROVIDER_DEFAULT",
    });

    expect(manifest.active_production_variants).toHaveLength(16);
    expect(manifest.execution_contracts).toHaveLength(56);
    expect(
      manifest.execution_contracts.every((contract) =>
        /^sha256:[0-9a-f]{64}$/.test(contract.structured_provider_contract_hash),
      ),
    ).toBe(true);
    expect(STRUCTURED_PROVIDER_CONTRACT_VERSION).toBe("structured_provider_contract_v2");
    const contractFor = (agent: string, language: "en" | "zh") => {
      const contract = manifest.execution_contracts.find(
        (candidate) => candidate.agent_id === agent && candidate.language === language,
      );
      if (!contract) throw new Error(`execution contract fixture missing: ${agent}:${language}`);
      return contract;
    };
    expect(contractFor("china", "zh").structured_provider_contract_hash).not.toBe(
      contractFor("geopolitical", "zh").structured_provider_contract_hash,
    );
    expect(
      contractFor("energy", "zh").structured_output_schema_bindings.map((binding) => binding.phase),
    ).toEqual(["DIRECTION_RESEARCH", "CONFLICT_REVIEW", "FINAL_SELECTION"]);
    expect(
      contractFor("cio", "en").structured_output_schema_bindings.map((binding) => binding.phase),
    ).toEqual(["CIO_PROPOSAL", "CIO_FINAL"]);
    expect(contractFor("china", "zh").structured_output_schema_bindings).toHaveLength(1);
    expect(contractFor("china", "zh").execution_behavior_version).not.toBe(
      contractFor("china", "en").execution_behavior_version,
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
    const before = baseline.execution_contracts.find(
      (contract) => contract.agent_id === "china" && contract.language === "zh",
    );
    const after = candidate.execution_contracts.find(
      (contract) => contract.agent_id === "china" && contract.language === "zh",
    );
    expect(candidate.private_prompt_bootstrap.prompt_tree_hash).not.toBe(
      baseline.private_prompt_bootstrap.prompt_tree_hash,
    );
    expect(after).toEqual(before);
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

  it("rejects a pinned private commit with an incomplete champion-state roster", () => {
    const fixture = promptFixture();
    const missing = join(
      fixture.privateRepoRoot,
      "registry/prompt_parameter_states_v1/cohort_default/agent_run/china.json",
    );
    rmSync(missing);
    git(fixture.privateRepoRoot, "add", "-A");
    git(fixture.privateRepoRoot, "commit", "-m", "remove one champion state");
    fixture.privatePromptCommit = git(fixture.privateRepoRoot, "rev-parse", "HEAD");

    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...fixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/state roster mismatch/);
  });

  it("rehashes the private parameter and behavior contracts instead of trusting declarations", () => {
    const parameterFixture = promptFixture();
    const parameterPath = join(
      parameterFixture.privateRepoRoot,
      "registry/knot/prompt_parameter_contract_v1.json",
    );
    const parameterContract = JSON.parse(readFileSync(parameterPath, "utf8"));
    writeFileSync(
      parameterPath,
      `${JSON.stringify({ ...parameterContract, contract_hash: `sha256:${"0".repeat(64)}` })}\n`,
    );
    git(parameterFixture.privateRepoRoot, "add", "registry/knot/prompt_parameter_contract_v1.json");
    git(parameterFixture.privateRepoRoot, "commit", "-m", "tamper parameter contract hash");
    parameterFixture.privatePromptCommit = git(
      parameterFixture.privateRepoRoot,
      "rev-parse",
      "HEAD",
    );
    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...parameterFixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/parameter contract hash mismatch/);

    const behaviorFixture = promptFixture();
    const behaviorPath = join(
      behaviorFixture.privateRepoRoot,
      "registry/knot/prompt_behavior_contract_v1.json",
    );
    const behaviorContract = JSON.parse(readFileSync(behaviorPath, "utf8"));
    writeFileSync(behaviorPath, `${JSON.stringify({ ...behaviorContract, tampered: true })}\n`);
    git(behaviorFixture.privateRepoRoot, "add", "registry/knot/prompt_behavior_contract_v1.json");
    git(behaviorFixture.privateRepoRoot, "commit", "-m", "tamper behavior contract");
    behaviorFixture.privatePromptCommit = git(behaviorFixture.privateRepoRoot, "rev-parse", "HEAD");
    expect(() =>
      buildExecutionBehaviorReleaseManifest({
        ...behaviorFixture,
        provider: "anthropic",
        model: "claude-sonnet-4",
        baseUrlMode: "PROVIDER_DEFAULT",
      }),
    ).toThrow(/behavior contract hash mismatch/);
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
    tampered.private_prompt_bootstrap.prompt_tree_hash = `sha256:${"0".repeat(64)}`;
    expect(() => validateExecutionBehaviorReleaseManifest(tampered)).toThrow();

    const providerTampered = structuredClone(manifest);
    const providerContract = providerTampered.execution_contracts[0];
    if (!providerContract) throw new Error("expected an execution contract");
    providerContract.structured_provider_contract_hash = `sha256:${"0".repeat(64)}`;
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
    ).toThrow(/every cohort must have distinct prompt behavior/);
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

  it("writes immutable candidates without creating a second production pointer", () => {
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
      archiveRoot,
    });
    writeExecutionBehaviorReleaseArtifacts({
      manifest: prepared,
      archiveRoot,
    });

    expect(existsSync(activeManifestPath)).toBe(false);
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
        archiveRoot,
      }),
    ).toThrow(/immutable execution behavior release archive collision/);
  });
});

function committedExecutionReleasePath(): string {
  const root = resolve(process.cwd(), "..");
  const contractRef = JSON.parse(
    readFileSync(
      resolve(root, "registry", "prompt_checks", "prompt_release_contract_ref_v2.json"),
      "utf8",
    ),
  ) as { sources: { execution_behavior_release_archive: { path: string } } };
  return resolve(root, contractRef.sources.execution_behavior_release_archive.path);
}

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
  writeBootstrapFixture(fixture.privateRepoRoot, fixture.privatePromptsRoot);
  git(fixture.privateRepoRoot, "add", "prompts/mosaic", "registry");
  git(fixture.privateRepoRoot, "commit", "-m", message);
  return git(fixture.privateRepoRoot, "rev-parse", "HEAD");
}

function writeBootstrapFixture(privateRepoRoot: string, privatePromptsRoot: string): void {
  const parameterContractBody = {
    schema_version: "prompt_parameter_contract_v1",
    parameters: [],
  };
  const parameterContract = {
    ...parameterContractBody,
    contract_hash: canonicalJsonHash(parameterContractBody),
  };
  const behaviorContract = {
    schema_version: "prompt_behavior_contract_v1",
    contracts: [],
  };
  const knotRoot = join(privateRepoRoot, "registry/knot");
  mkdirSync(knotRoot, { recursive: true });
  writeFileSync(
    join(knotRoot, "prompt_parameter_contract_v1.json"),
    `${JSON.stringify(parameterContract, null, 2)}\n`,
  );
  writeFileSync(
    join(knotRoot, "prompt_behavior_contract_v1.json"),
    `${JSON.stringify(behaviorContract, null, 2)}\n`,
  );
  const stateFiles = MACRO_PROMPT_COHORT_IDS.flatMap((cohort) =>
    ALL_AGENTS.map((agent) => {
      const ref = `registry/prompt_parameter_states_v1/${cohort}/${parameterStage(agent)}/${agent}.json`;
      const content = `${JSON.stringify({ agent, cohort, stage: parameterStage(agent) })}\n`;
      const path = join(privateRepoRoot, ref);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, content);
      return { ref, content_hash: textHash(content) };
    }),
  ).sort((left, right) => left.ref.localeCompare(right.ref));
  const promptFiles = MACRO_PROMPT_COHORT_IDS.flatMap((cohort) =>
    ALL_AGENTS.flatMap((agent) =>
      (["en", "zh"] as const).map((language) => {
        const path = promptPath({ agent, cohort, language, promptsRoot: privatePromptsRoot });
        const ref = relative(privateRepoRoot, path).replaceAll("\\", "/");
        return { ref, content_hash: textHash(readFileSync(path, "utf8")) };
      }),
    ),
  ).sort((left, right) => left.ref.localeCompare(right.ref));
  const body = {
    schema_version: "private_prompt_parameter_bootstrap_release_v1" as const,
    parameter_contract_hash: parameterContract.contract_hash,
    behavior_contract_hash: canonicalJsonHash(behaviorContract),
    agent_count: 28 as const,
    cohort_count: 8 as const,
    state_count: 224 as const,
    prompt_count: 448 as const,
    state_tree_hash: canonicalJsonHash({ files: stateFiles }),
    prompt_tree_hash: canonicalJsonHash({ files: promptFiles }),
  };
  const path = join(privateRepoRoot, "registry/knot/prompt_parameter_bootstrap_release_v1.json");
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(
    path,
    `${JSON.stringify({ ...body, release_hash: canonicalJsonHash(body) }, null, 2)}\n`,
  );
}

function parameterStage(agent: string): string {
  if (agent === "alpha_discovery") return "alpha_discovery";
  if (agent === "autonomous_execution") return "execution_feasibility";
  if (agent === "cio") return "cio_final";
  if (agent === "cro") return "cro_review";
  return "agent_run";
}

function textHash(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
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

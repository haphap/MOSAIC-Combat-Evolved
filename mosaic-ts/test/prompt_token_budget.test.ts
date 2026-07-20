import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { LAYER_BY_AGENT } from "../src/agents/prompts/cohorts.js";
import {
  buildPromptTokenBudgetManifest,
  PromptTokenBudgetManifestSchema,
  promptTokenBudgetManifestHash,
} from "../src/agents/prompts/prompt_token_budget.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

interface FixtureRoots {
  privateRoot: string;
  bundledRoot: string;
  privateCommit: string;
  bundledCommit: string;
}

function fixtureRoots(): FixtureRoots {
  const root = mkdtempSync(join(tmpdir(), "mosaic-prompt-budget-"));
  roots.push(root);
  const privateRoot = join(root, "private", "prompts", "mosaic");
  const bundledRoot = join(root, "bundled", "prompts", "mosaic");
  for (const promptsRoot of [privateRoot, bundledRoot]) {
    for (const spec of RUNTIME_AGENT_SPECS) {
      const layer = LAYER_BY_AGENT[spec.agent];
      if (!layer) throw new Error(`missing layer for ${spec.agent}`);
      const directory = join(promptsRoot, "cohort_default", layer);
      mkdirSync(directory, { recursive: true });
      for (const language of ["zh", "en"] as const) {
        writeFileSync(
          join(directory, `${spec.agent}.${language}.md`),
          `# ${spec.agent} ${language}\nRuntime contract body.\n`,
          "utf-8",
        );
      }
    }
  }
  const privateCommit = initializeRepository(join(root, "private"));
  const bundledCommit = initializeRepository(join(root, "bundled"));
  return { privateRoot, bundledRoot, privateCommit, bundledCommit };
}

async function build(
  roots: FixtureRoots,
  baseline: Awaited<ReturnType<typeof buildPromptTokenBudgetManifest>> | null = null,
) {
  return buildPromptTokenBudgetManifest({
    cohort: "cohort_default",
    privatePromptsRoot: roots.privateRoot,
    bundledPromptsRoot: roots.bundledRoot,
    privateCommit: roots.privateCommit,
    bundledCommit: roots.bundledCommit,
    generatedAt: "2026-07-10T00:00:00.000Z",
    baseline,
  });
}

describe("prompt token budget manifest", () => {
  it("measures both sources for all 29 runtime stages and both languages", async () => {
    const artifact = await build(fixtureRoots());

    expect(artifact.summary).toEqual({
      expected_row_count: 116,
      row_count: 116,
      passed_row_count: 116,
      failed_row_count: 0,
      semantic_parity_passed: true,
      ready: true,
    });
    expect(new Set(artifact.rows.map((row) => row.source))).toEqual(
      new Set(["private", "bundled"]),
    );
    expect(PromptTokenBudgetManifestSchema.parse(artifact)).toEqual(artifact);
  });

  it("fails when a runtime prompt grows beyond the committed 1.25x baseline", async () => {
    const roots = fixtureRoots();
    const baseline = await build(roots);
    const path = join(
      roots.privateRoot,
      "cohort_default",
      "macro",
      "us_financial_conditions.zh.md",
    );
    writeFileSync(path, `${readFileSync(path, "utf-8")}\n${"expanded contract ".repeat(8_000)}`);
    roots.privateCommit = commitRepository(join(roots.privateRoot, "..", ".."), "grow prompt");

    const current = await build(roots, baseline);

    const failed = current.rows.filter((row) => !row.passed);
    expect(current.summary.ready).toBe(false);
    expect(failed.length).toBeGreaterThan(0);
    expect(failed.some((row) => !row.checks.baseline_growth_within_limit)).toBe(true);
  });

  it("keeps a complete prompt-topology baseline across opaque runtime pin rotation", async () => {
    const roots = fixtureRoots();
    const baseline = await build(roots);
    const rotated = {
      ...baseline,
      runtime_manifest_hash: `sha256:${"f".repeat(64)}`,
    };
    rotated.manifest_hash = promptTokenBudgetManifestHash(rotated);

    const current = await build(roots, PromptTokenBudgetManifestSchema.parse(rotated));

    expect(current.baseline_manifest_hash).toBe(rotated.manifest_hash);
    expect(current.rows.every((row) => row.baseline_growth_ratio === 1)).toBe(true);
  });

  it("rejects a baseline with an incomplete prompt topology", async () => {
    const roots = fixtureRoots();
    const baseline = await build(roots);
    const rows = baseline.rows.slice(1);
    const incomplete = {
      ...baseline,
      rows,
      summary: {
        ...baseline.summary,
        row_count: rows.length,
        passed_row_count: rows.length,
        ready: false,
      },
    };
    incomplete.manifest_hash = promptTokenBudgetManifestHash(incomplete);

    await expect(build(roots, PromptTokenBudgetManifestSchema.parse(incomplete))).rejects.toThrow(
      "prompt_token_budget_baseline_configuration_mismatch",
    );
  });

  it("rejects source content that does not match the attributed commits", async () => {
    const roots = fixtureRoots();
    const path = join(roots.bundledRoot, "cohort_default", "macro", "china.en.md");
    writeFileSync(path, `${readFileSync(path, "utf-8")}\nuncommitted change\n`, "utf-8");

    await expect(build(roots)).rejects.toThrow("prompt_source_tree_drift:bundled");
  });
});

function initializeRepository(root: string): string {
  git(root, "init", "-b", "main");
  git(root, "config", "user.name", "Test");
  git(root, "config", "user.email", "test@example.com");
  return commitRepository(root, "seed prompts");
}

function commitRepository(root: string, message: string): string {
  git(root, "add", "prompts/mosaic");
  git(root, "commit", "-m", message);
  return git(root, "rev-parse", "HEAD");
}

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-C", cwd, ...args], { encoding: "utf8" }).trim();
}

import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { renderResearchKnobsFence } from "../src/agents/helpers/research_knobs.js";
import { LAYER_BY_AGENT } from "../src/agents/prompts/cohorts.js";
import {
  buildPromptTokenBudgetManifest,
  PromptTokenBudgetManifestSchema,
} from "../src/agents/prompts/prompt_token_budget.js";
import { buildRuntimeResearchKnobs } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixtureRoots(): { privateRoot: string; bundledRoot: string } {
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
      const fence = renderResearchKnobsFence(buildRuntimeResearchKnobs(spec));
      for (const language of ["zh", "en"] as const) {
        writeFileSync(
          join(directory, `${spec.agent}.${language}.md`),
          `${fence}\n\n# ${spec.agent} ${language}\nRuntime contract body.\n`,
          "utf-8",
        );
      }
    }
  }
  return { privateRoot, bundledRoot };
}

async function build(
  roots: { privateRoot: string; bundledRoot: string },
  baseline: Awaited<ReturnType<typeof buildPromptTokenBudgetManifest>> | null = null,
) {
  return buildPromptTokenBudgetManifest({
    cohort: "cohort_default",
    privatePromptsRoot: roots.privateRoot,
    bundledPromptsRoot: roots.bundledRoot,
    privateCommit: "a".repeat(40),
    bundledCommit: "b".repeat(40),
    generatedAt: "2026-07-10T00:00:00.000Z",
    baseline,
  });
}

describe("prompt token budget manifest", () => {
  it("measures both sources for all 26 runtime stages and both languages", async () => {
    const artifact = await build(fixtureRoots());

    expect(artifact.summary).toEqual({
      expected_row_count: 104,
      row_count: 104,
      passed_row_count: 104,
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
    const path = join(roots.privateRoot, "cohort_default", "macro", "volatility.zh.md");
    writeFileSync(path, `${readFileSync(path, "utf-8")}\n${"expanded contract ".repeat(8_000)}`);

    const current = await build(roots, baseline);

    const failed = current.rows.filter((row) => !row.passed);
    expect(current.summary.ready).toBe(false);
    expect(failed.length).toBeGreaterThan(0);
    expect(failed.some((row) => !row.checks.baseline_growth_within_limit)).toBe(true);
  });

  it("fails source semantic parity when private knobs drift", async () => {
    const roots = fixtureRoots();
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "volatility");
    if (!spec) throw new Error("volatility spec missing");
    const knobs = structuredClone(buildRuntimeResearchKnobs(spec));
    const missing = knobs.confidence_caps.missing_current_data;
    if (!missing) throw new Error("missing current-data cap missing");
    missing.cap = 0.5;
    const fence = renderResearchKnobsFence(knobs);
    for (const language of ["zh", "en"] as const) {
      writeFileSync(
        join(roots.privateRoot, "cohort_default", "macro", `volatility.${language}.md`),
        `${fence}\n\n# volatility ${language}\nRuntime contract body.\n`,
      );
    }

    const artifact = await build(roots);

    expect(artifact.summary.semantic_parity_passed).toBe(false);
    expect(artifact.summary.ready).toBe(false);
  });
});

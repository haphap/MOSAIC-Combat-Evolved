import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  AGENTS_BY_LAYER,
  ALL_AGENTS,
  findBundledPromptsRoot,
  findPrivatePromptsRoot,
  findPromptsRoot,
  LAYER_BY_AGENT,
  promptPath,
  resolvePromptPath,
} from "../src/agents/prompts/cohorts.js";
import {
  clearPromptCache,
  loadPrompt,
  loadPromptWithPrivateKnot,
  PromptNotFoundError,
} from "../src/agents/prompts/loader.js";
import { installTestPrivateKnotRuntime } from "./helpers/private_knot.js";

const TEST_KNOT_INVOCATION = {
  invocation_mode: "NON_PRODUCTION_TEST",
  graph_run_id: "prompt-loader-test-run",
  as_of: "2026-07-09",
  execution_behavior_release_id: "non-production-test",
} as const;

interface FakeRoot {
  root: string;
  cleanup: () => void;
  /** Drop a markdown file at ``<cohort>/<layer>/<agent>.<lang>.md``. */
  putPrompt(opts: {
    cohort: string;
    layer: string;
    agent: string;
    language: "zh" | "en";
    body: string;
  }): string;
}

function makeFakePromptsRoot(): FakeRoot {
  const root = mkdtempSync(join(tmpdir(), "mosaic-prompts-test-"));
  return {
    root,
    cleanup: () => rmSync(root, { recursive: true, force: true }),
    putPrompt({ cohort, layer, agent, language, body }) {
      const dir = join(root, cohort, layer);
      mkdirSync(dir, { recursive: true });
      const path = join(dir, `${agent}.${language}.md`);
      writeFileSync(path, body, "utf-8");
      return path;
    },
  };
}

function makeFakePromptRepo(): FakeRoot {
  const repoRoot = mkdtempSync(join(tmpdir(), "mosaic-prompts-repo-test-"));
  const root = join(repoRoot, "prompts", "mosaic");
  return {
    root: repoRoot,
    cleanup: () => rmSync(repoRoot, { recursive: true, force: true }),
    putPrompt({ cohort, layer, agent, language, body }) {
      const dir = join(root, cohort, layer);
      mkdirSync(dir, { recursive: true });
      const path = join(dir, `${agent}.${language}.md`);
      writeFileSync(path, body, "utf-8");
      return path;
    },
  };
}

describe("AGENTS_BY_LAYER + LAYER_BY_AGENT (Plan §5)", () => {
  it("covers exactly the 28 v2 agents", () => {
    expect(AGENTS_BY_LAYER.macro).toHaveLength(10);
    expect(AGENTS_BY_LAYER.sector).toHaveLength(10);
    expect(AGENTS_BY_LAYER.superinvestor).toHaveLength(4);
    expect(AGENTS_BY_LAYER.decision).toHaveLength(4);
    expect(ALL_AGENTS).toHaveLength(28);
    expect(new Set(ALL_AGENTS).size).toBe(28);
  });

  it("LAYER_BY_AGENT inverse map is consistent", () => {
    for (const [layer, agents] of Object.entries(AGENTS_BY_LAYER)) {
      for (const agent of agents) {
        expect(LAYER_BY_AGENT[agent]).toBe(layer);
      }
    }
  });
});

describe("promptPath", () => {
  it("uses the agent's canonical layer when omitted", () => {
    const p = promptPath({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: "/tmp/x",
    });
    expect(p).toBe("/tmp/x/cohort_default/macro/central_bank.zh.md");
  });

  it("rejects an unknown agent", () => {
    expect(() =>
      promptPath({
        agent: "no_such_agent",
        cohort: "cohort_default",
        language: "zh",
        promptsRoot: "/tmp/x",
      }),
    ).toThrow(/Unknown agent/);
  });
});

describe("resolvePromptPath fallback chain", () => {
  let fake: FakeRoot;
  let privateFake: FakeRoot;
  let oldPrivateRepo: string | undefined;
  let oldPromptsRepo: string | undefined;
  let oldPromptsRoot: string | undefined;
  beforeEach(() => {
    oldPrivateRepo = process.env.MOSAIC_PRIVATE_PROMPT_REPO;
    oldPromptsRepo = process.env.MOSAIC_PROMPTS_REPO;
    oldPromptsRoot = process.env.MOSAIC_PROMPTS_ROOT;
    delete process.env.MOSAIC_PRIVATE_PROMPT_REPO;
    delete process.env.MOSAIC_PROMPTS_REPO;
    delete process.env.MOSAIC_PROMPTS_ROOT;
    fake = makeFakePromptsRoot();
    privateFake = makeFakePromptsRoot();
    installTestPrivateKnotRuntime();
    clearPromptCache();
  });
  afterEach(() => {
    fake?.cleanup();
    privateFake?.cleanup();
    if (oldPrivateRepo === undefined) {
      delete process.env.MOSAIC_PRIVATE_PROMPT_REPO;
    } else {
      process.env.MOSAIC_PRIVATE_PROMPT_REPO = oldPrivateRepo;
    }
    if (oldPromptsRepo === undefined) {
      delete process.env.MOSAIC_PROMPTS_REPO;
    } else {
      process.env.MOSAIC_PROMPTS_REPO = oldPromptsRepo;
    }
    if (oldPromptsRoot === undefined) {
      delete process.env.MOSAIC_PROMPTS_ROOT;
    } else {
      process.env.MOSAIC_PROMPTS_ROOT = oldPromptsRoot;
    }
  });

  it("returns the cohort-specific file when present", () => {
    const expected = fake.putPrompt({
      cohort: "cohort_euphoria_2021",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "cohort prompt",
    });
    // Add a default fallback to prove the cohort-specific one wins.
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "default prompt",
    });
    const found = resolvePromptPath({
      agent: "central_bank",
      cohort: "cohort_euphoria_2021",
      language: "zh",
      promptsRoot: fake.root,
    });
    expect(found).toBe(expected);
  });

  it("falls back to cohort_default when the cohort-specific is missing", () => {
    const expected = fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "default body",
    });
    const found = resolvePromptPath({
      agent: "central_bank",
      cohort: "cohort_euphoria_2021",
      language: "zh",
      promptsRoot: fake.root,
    });
    expect(found).toBe(expected);
  });

  it("returns null when neither candidate exists", () => {
    const found = resolvePromptPath({
      agent: "central_bank",
      cohort: "cohort_euphoria_2021",
      language: "zh",
      promptsRoot: fake.root,
    });
    expect(found).toBeNull();
  });

  it("prefers private cohort prompt over repo prompts", () => {
    fake.putPrompt({
      cohort: "cohort_euphoria_2021",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "repo cohort",
    });
    const expected = privateFake.putPrompt({
      cohort: "cohort_euphoria_2021",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "private cohort",
    });
    const found = resolvePromptPath({
      agent: "central_bank",
      cohort: "cohort_euphoria_2021",
      language: "zh",
      promptsRoot: fake.root,
      privatePromptsRoot: privateFake.root,
    });
    expect(found).toBe(expected);
  });

  it("accepts a private prompt repo root as an explicit privatePromptsRoot", () => {
    const privateRepo = makeFakePromptRepo();
    try {
      const expected = privateRepo.putPrompt({
        cohort: "cohort_default",
        layer: "macro",
        agent: "central_bank",
        language: "zh",
        body: "private repo root",
      });
      const found = resolvePromptPath({
        agent: "central_bank",
        cohort: "cohort_default",
        language: "zh",
        promptsRoot: fake.root,
        privatePromptsRoot: privateRepo.root,
      });
      expect(found).toBe(expected);
    } finally {
      privateRepo.cleanup();
    }
  });

  it("prefers private default prompt over repo cohort prompt", () => {
    fake.putPrompt({
      cohort: "cohort_euphoria_2021",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "repo cohort",
    });
    const expected = privateFake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "private default",
    });
    const found = resolvePromptPath({
      agent: "central_bank",
      cohort: "cohort_euphoria_2021",
      language: "zh",
      promptsRoot: fake.root,
      privatePromptsRoot: privateFake.root,
    });
    expect(found).toBe(expected);
  });

  it("derives the private prompt root from MOSAIC_PRIVATE_PROMPT_REPO", () => {
    process.env.MOSAIC_PRIVATE_PROMPT_REPO = "/tmp/private-prompts";
    expect(findPrivatePromptsRoot()).toBe("/tmp/private-prompts/prompts/mosaic");
  });

  it("keeps bundled prompts as the default prompt root", () => {
    process.env.MOSAIC_PROMPTS_REPO = "/tmp/MOSAIC-Prompts";
    expect(findPromptsRoot()).toBe(findBundledPromptsRoot());
  });

  it("derives the private prompt root from MOSAIC_PROMPTS_REPO", () => {
    process.env.MOSAIC_PROMPTS_REPO = "/tmp/MOSAIC-Prompts";
    expect(findPrivatePromptsRoot()).toBe("/tmp/MOSAIC-Prompts/prompts/mosaic");
  });

  it("lets MOSAIC_PROMPTS_ROOT point directly at prompts/mosaic", () => {
    process.env.MOSAIC_PROMPTS_REPO = "/tmp/MOSAIC-Prompts";
    process.env.MOSAIC_PROMPTS_ROOT = "/tmp/direct-prompts-root";
    expect(findPrivatePromptsRoot()).toBe("/tmp/direct-prompts-root");
  });

  it("prefers MOSAIC_PROMPTS_ROOT when no promptsRoot is passed", () => {
    const expected = fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "external root body",
    });
    process.env.MOSAIC_PROMPTS_ROOT = fake.root;

    const found = resolvePromptPath({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
    });
    expect(found).toBe(expected);
  });
});

describe("loadPrompt", () => {
  let fake: FakeRoot;
  let privateFake: FakeRoot;
  let oldPrivateRepo: string | undefined;
  beforeEach(() => {
    oldPrivateRepo = process.env.MOSAIC_PRIVATE_PROMPT_REPO;
    delete process.env.MOSAIC_PRIVATE_PROMPT_REPO;
    fake = makeFakePromptsRoot();
    privateFake = makeFakePromptsRoot();
    clearPromptCache();
  });
  afterEach(() => {
    fake?.cleanup();
    privateFake?.cleanup();
    if (oldPrivateRepo === undefined) {
      delete process.env.MOSAIC_PRIVATE_PROMPT_REPO;
    } else {
      process.env.MOSAIC_PRIVATE_PROMPT_REPO = oldPrivateRepo;
    }
  });

  it("loads the file body verbatim", async () => {
    const body = "# central_bank\n\nzh body line";
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body,
    });
    const out = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fake.root,
    });
    expect(out).toBe(body);
  });

  it("falls back to cohort_default for non-default cohorts", async () => {
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "en",
      body: "EN body from default",
    });
    const out = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_euphoria_2021",
      language: "en",
      promptsRoot: fake.root,
    });
    expect(out).toBe("EN body from default");
  });

  it("Bilingual concatenates zh + '---' + en", async () => {
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "ZH",
    });
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "en",
      body: "EN",
    });
    const out = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "Bilingual",
      promptsRoot: fake.root,
    });
    expect(out).toBe("ZH\n\n---\n\nEN");
  });

  it("Bilingual tolerates one missing leg", async () => {
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "ZH only",
    });
    const out = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "Bilingual",
      promptsRoot: fake.root,
    });
    expect(out).toBe("ZH only");
  });

  it("throws PromptNotFoundError when neither candidate exists", async () => {
    await expect(
      loadPrompt({
        agent: "central_bank",
        cohort: "cohort_euphoria_2021",
        language: "zh",
        promptsRoot: fake.root,
      }),
    ).rejects.toBeInstanceOf(PromptNotFoundError);
  });

  it("redacts private prompt paths from PromptNotFoundError", async () => {
    const privateRoot = join(tmpdir(), "private-prompts-sensitive", "prompts", "mosaic");

    try {
      await loadPrompt({
        agent: "central_bank",
        cohort: "cohort_euphoria_2021",
        language: "zh",
        promptsRoot: fake.root,
        privatePromptsRoot: privateRoot,
      });
      throw new Error("expected loadPrompt to fail");
    } catch (err) {
      expect(err).toBeInstanceOf(PromptNotFoundError);
      expect((err as Error).message).toContain("<private-prompt-repo>");
      expect((err as Error).message).not.toContain(privateRoot);
      expect((err as PromptNotFoundError).triedPaths.join("\n")).not.toContain(privateRoot);
    }
  });

  it("caches by (cohort, agent, language); noCache bypasses", async () => {
    const path = fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "v1",
    });

    const first = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fake.root,
    });
    expect(first).toBe("v1");

    // Mutate on disk; cached read still returns v1.
    writeFileSync(path, "v2", "utf-8");
    const cached = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fake.root,
    });
    expect(cached).toBe("v1");

    // noCache bypass yields v2.
    const fresh = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fake.root,
      noCache: true,
    });
    expect(fresh).toBe("v2");
  });

  it("loads private overlay without poisoning the baseline cache", async () => {
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "baseline",
    });
    privateFake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "private",
    });

    const baseline = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fake.root,
    });
    const overlay = await loadPrompt({
      agent: "central_bank",
      cohort: "cohort_default",
      language: "zh",
      promptsRoot: fake.root,
      privatePromptsRoot: privateFake.root,
    });

    expect(baseline).toBe("baseline");
    expect(overlay).toBe("private");
  });

  it("binds a fence-free prompt pair to an opaque private snapshot", async () => {
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "ZH body",
    });
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "en",
      body: "EN body",
    });

    const out = await loadPromptWithPrivateKnot({
      invocationContext: TEST_KNOT_INVOCATION,
      agent: "central_bank",
      cohort: "cohort_default",
      stage: "agent_run",
      promptsRoot: fake.root,
    });

    expect(out.prompt).toContain("ZH body");
    expect(out.prompt).toContain("EN body");
    expect(out.prompt).not.toContain("```research-knobs");
    expect(out.snapshot.snapshot_hash).toMatch(/^sha256:/);
    expect(out.snapshot).not.toHaveProperty("knobs");
  });

  it("fails closed when one language is missing", async () => {
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "ZH body",
    });

    await expect(
      loadPromptWithPrivateKnot({
        invocationContext: TEST_KNOT_INVOCATION,
        agent: "central_bank",
        cohort: "cohort_default",
        promptsRoot: fake.root,
      }),
    ).rejects.toBeInstanceOf(PromptNotFoundError);
  });

  it("never fills a missing private KNOT prompt leg from the bundled root", async () => {
    privateFake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: "private ZH",
    });
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "en",
      body: "bundled EN",
    });

    await expect(
      loadPromptWithPrivateKnot({
        invocationContext: TEST_KNOT_INVOCATION,
        agent: "central_bank",
        cohort: "cohort_default",
        promptsRoot: fake.root,
        privatePromptsRoot: privateFake.root,
      }),
    ).rejects.toBeInstanceOf(PromptNotFoundError);
  });

  it("requires a pinned private release for formal KNOT traffic", async () => {
    for (const language of ["zh", "en"] as const) {
      fake.putPrompt({
        cohort: "cohort_default",
        layer: "macro",
        agent: "central_bank",
        language,
        body: `${language} body`,
      });
    }
    await expect(
      loadPromptWithPrivateKnot({
        invocationContext: TEST_KNOT_INVOCATION,
        agent: "central_bank",
        cohort: "cohort_default",
        promptsRoot: fake.root,
        requirePinnedPrivateRelease: true,
      }),
    ).rejects.toThrow("private_knot_prompt_release_required");
  });

  it.each([
    "```research-knobs\nprivate: true\n```",
    "confidence cap",
    "evidence_weights",
    "Darwinian",
    "darwin",
    "knot",
    "mutation target",
    "champion behavior",
    "研究旋钮",
    "研究规则 ID",
    "证据权重",
    "晋级门槛",
  ])("rejects embedded private policy content: %s", async (marker) => {
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "zh",
      body: `${marker}\nZH body`,
    });
    fake.putPrompt({
      cohort: "cohort_default",
      layer: "macro",
      agent: "central_bank",
      language: "en",
      body: "EN body",
    });

    await expect(
      loadPromptWithPrivateKnot({
        invocationContext: TEST_KNOT_INVOCATION,
        agent: "central_bank",
        cohort: "cohort_default",
        promptsRoot: fake.root,
      }),
    ).rejects.toThrow(/private_knot_content_embedded/);
  });
});

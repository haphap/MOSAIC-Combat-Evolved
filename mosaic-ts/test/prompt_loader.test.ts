import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  AGENTS_BY_LAYER,
  ALL_AGENTS,
  findPrivatePromptsRoot,
  LAYER_BY_AGENT,
  promptPath,
  resolvePromptPath,
} from "../src/agents/prompts/cohorts.js";
import { clearPromptCache, loadPrompt, PromptNotFoundError } from "../src/agents/prompts/loader.js";

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

describe("AGENTS_BY_LAYER + LAYER_BY_AGENT (Plan §5)", () => {
  it("covers exactly the 25 agents from Plan §5", () => {
    expect(AGENTS_BY_LAYER.macro).toHaveLength(10);
    expect(AGENTS_BY_LAYER.sector).toHaveLength(7);
    expect(AGENTS_BY_LAYER.superinvestor).toHaveLength(4);
    expect(AGENTS_BY_LAYER.decision).toHaveLength(4);
    expect(ALL_AGENTS).toHaveLength(25);
    expect(new Set(ALL_AGENTS).size).toBe(25);
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
});
